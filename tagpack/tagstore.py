# -*- coding: utf-8 -*-
import os
from datetime import datetime

import numpy as np
from psycopg2 import connect
from psycopg2.extensions import register_adapter, AsIs
from psycopg2.extras import execute_batch

register_adapter(np.int64, AsIs)


class TagStore(object):
    def __init__(self, url, schema):
        self.conn = connect(url, options=f"-c search_path={schema}")
        self.cursor = self.conn.cursor()

        self.cursor.execute("SELECT unnest(enum_range(NULL::currency))")
        self.supported_currencies = [i[0] for i in self.cursor.fetchall()]
        self.existing_packs = None

    def insert_taxonomy(self, taxonomy):
        self.cursor.execute("""INSERT INTO taxonomy (id, source, description) VALUES (%s, %s, %s)""", (taxonomy.key, taxonomy.uri, f"Imported at {datetime.now().isoformat()}"))

        for c in taxonomy.concepts:
            self.cursor.execute("""INSERT INTO concept (id, label, taxonomy, source, description) VALUES (%s, %s, %s, %s, %s)""", (c.id, c.label, c.taxonomy.key, c.uri, c.description))

        self.conn.commit()

    def insert_confidence_scores(self, confidence, force):
        statement = "INSERT INTO confidence (id, label, description, level)"
        statement += " VALUES (%s, %s, %s, %s)"

        # TODO What to do with foreign key restrictions?
#        if force:
#            print(f"evicting and re-inserting all confidence scores")
#            self.cursor.execute("DELETE FROM confidence")

        for c in confidence.scores:
            values = (c.id, c.label, c.description, c.level)
            self.cursor.execute(statement, values)

        self.conn.commit()

    def tp_exists(self, prefix, rel_path):
        if not self.existing_packs:
            self.existing_packs = self.get_ingested_tagpacks()
        return self.create_id(prefix, rel_path) in self.existing_packs

    def create_id(self, prefix, rel_path):
        return ":".join([prefix, rel_path]) if prefix else rel_path

    def insert_tagpack(self, tagpack, is_public, force_insert, prefix, rel_path, batch=1000):
        tagpack_id = self.create_id(prefix, rel_path)
        h = _get_header(tagpack, tagpack_id)

        if force_insert:
            print(f"evicting and re-inserting tagpack {tagpack_id}")
            self.cursor.execute("DELETE FROM tagpack WHERE id = (%s)", (tagpack_id,))
        self.cursor.execute("INSERT INTO tagpack (id, title, description, creator, uri, is_public) VALUES (%s,%s,%s,%s,%s,%s)", (h.get('id'), h.get('title'), h.get('description'), h.get('creator'), tagpack.uri, is_public))
        self.conn.commit()

        addr_sql = "INSERT INTO address (currency, address) VALUES (%s, %s) ON CONFLICT DO NOTHING"
        tag_sql = "INSERT INTO tag (label, source, category, abuse, address, currency, is_cluster_definer, confidence, lastmod, context, tagpack ) VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)"

        tag_data = []
        address_data = []
        for tag in tagpack.get_unique_tags():
            if self._supports_currency(tag):
                tag_data.append(_get_tag(tag, tagpack_id))
                address_data.append(_get_currency_and_address(tag))
            if len(tag_data) > batch:
                execute_batch(self.cursor, addr_sql, address_data)
                execute_batch(self.cursor, tag_sql, tag_data)

                tag_data = []
                address_data = []

        # insert remaining items
        execute_batch(self.cursor, addr_sql, address_data)
        execute_batch(self.cursor, tag_sql, tag_data)

        self.conn.commit()

    def remove_duplicates(self):
        self.cursor.execute("""
            DELETE
                FROM tag
                WHERE id IN
                (
                    SELECT id FROM
                        (SELECT
                            t.id,
                            t.address,
                            t.label,
                            t.source,
                            tp.creator,
                            ROW_NUMBER() OVER (PARTITION BY t.address,
                                t.label,
                                t.source,
                                tp.creator ORDER BY t.id DESC)
                                    AS duplicate_count
                        FROM
                            tag t,
                            tagpack tp
                        WHERE
                            t.tagpack = tp.id) as x
                    WHERE duplicate_count > 1
                )
            """)
        self.conn.commit()
        return self.cursor.rowcount

    def refresh_db(self):
        self.cursor.execute('REFRESH MATERIALIZED VIEW label')
        self.cursor.execute('REFRESH MATERIALIZED VIEW statistics')
        self.cursor.execute('REFRESH MATERIALIZED VIEW tag_count_by_cluster')
        self.cursor.execute('REFRESH MATERIALIZED VIEW cluster_defining_tags_by_frequency_and_maxconfidence') # noqa
        self.conn.commit()

    def get_addresses(self, update_existing):
        if update_existing:
            self.cursor.execute("SELECT address, currency FROM address")
        else:
            self.cursor.execute("SELECT address, currency FROM address WHERE NOT is_mapped")
        for record in self.cursor:
            yield record

    def insert_cluster_mappings(self, clusters):
        if not clusters.empty:
            q = "INSERT INTO address_cluster_mapping (address, currency, gs_cluster_id , gs_cluster_def_addr , gs_cluster_no_addr )" \
                "VALUES (%s, %s, %s, %s, %s) ON CONFLICT (currency, address) DO UPDATE SET " \
                "gs_cluster_id = EXCLUDED.gs_cluster_id , gs_cluster_def_addr = EXCLUDED.gs_cluster_def_addr , gs_cluster_no_addr = EXCLUDED.gs_cluster_no_addr  "

            data = clusters[['address', 'currency', 'cluster_id', 'cluster_defining_address', 'no_addresses']].to_records(index=False)

            execute_batch(self.cursor, q, data)
            self.conn.commit()

    def _supports_currency(self, tag):
        return tag.all_fields.get('currency') in self.supported_currencies

    def finish_mappings_update(self, keys):
        self.cursor.execute('UPDATE address SET is_mapped=true WHERE NOT is_mapped AND currency IN %s', (tuple(keys),))
        self.conn.commit()

    def get_ingested_tagpacks(self) -> list:
        self.cursor.execute("SELECT id from tagpack")
        return [i[0] for i in self.cursor.fetchall()]

    def get_quality_measures(self, currency='') -> float:
        '''
        This function returns a dict with the quality measures (count, avg, and
        stddev) for a specific currency, or for all if currency is not
        specified.
        '''
        currency = currency.upper()
        if currency not in ['', 'BCH', 'BTC', 'ETH', 'LTC', 'ZEC']:
            raise ValidationError("Currency not supported: {currency}")

        query = 'SELECT COUNT(quality), AVG(quality), STDDEV(quality)'
        query += ' FROM address_quality'
        if currency:
            query += ' WHERE currency=%s'
            self.cursor.execute(query, (currency,))
        else:
            self.cursor.execute(query)

        keys = ['count', 'avg', 'stddev']
        return {keys[i]:v for row in self.cursor.fetchall() \
                    for i,v in enumerate(row)}

    def calculate_quality_measures(self) -> float:
        self.cursor.execute("CALL calculate_quality()")
        self.cursor.execute("CALL insert_address_quality()")
        self.conn.commit()
        return self.get_quality_measures()


def _get_tag(tag, tagpack_id):
    label = tag.all_fields.get('label').lower().strip()
    lastmod = tag.all_fields.get('lastmod', datetime.now().isoformat())

    _, address = _get_currency_and_address(tag)

    return (label, tag.all_fields.get('source'), tag.all_fields.get('category', None),
            tag.all_fields.get('abuse', None), address, tag.all_fields.get('currency'),
            tag.all_fields.get('is_cluster_definer'), tag.all_fields.get('confidence'),
            lastmod, tag.all_fields.get('context'), tagpack_id)


def _get_currency_and_address(tag):
    curr = tag.all_fields.get('currency')
    addr = tag.all_fields.get('address')
    addr = addr.lower() if 'ETH' == curr.upper() else addr
    return curr, addr


def _get_header(tagpack, tid):
    tc = tagpack.contents
    return {
        'id': tid,
        'title': tc['title'],
#        'source': tc.get('source', os.path.split(tagpack.tags[0].all_fields.get('source'))[0]),
        'creator': tc['creator'],
        'description': tc.get('description', 'not provided'),
#        'owner': tc.get('owner', 'unknown')
        }

