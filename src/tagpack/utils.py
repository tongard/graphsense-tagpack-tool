import importlib.resources as pkg_resources
import os
from datetime import datetime
from urllib.parse import urlparse

from . import conf, db


def strip_values(listlike, values):
    return [x for x in listlike if x not in values]


def strip_none(listlike):
    return strip_values(listlike, [None])


def strip_empty(listlike):
    return strip_values(listlike, [None, "", []])


def try_parse_date(date, format="%Y-%m-%d"):
    """Trys to parse a date from a given object.

    Args:
        date (object): Description
        format (str, optional): date format string

    Returns:
        Union[str|object]: Either returns a parsed date or the original object
    """
    if date is not None and type(date) == str:
        try:
            return datetime.strptime(date, format)
        except ValueError:
            return date
    else:
        return date


def apply_to_dict_field(dictlike, field: str, fun, fail=True):
    """Summary

    Args:
        dictlike (dict): something dict like
        field (str): Field to apply the function on
        fun (Function): Function to apply, must take one parameter
        fail (bool, optional): If True the function throws and error
        if field is not present

    Raises:
        ValueError: Description
    """
    if field in dictlike:
        dictlike[field] = fun(dictlike[field])
    elif fail:
        raise ValueError(f"Field {field} is not present in dictionary.")


def get_secondlevel_domain(url: str) -> str:
    """Summary

    Args:
        url (str): url to parse

    Returns:
        str: top level domain
    """
    if not url.startswith("http"):
        url = f"http://{url}"
    pu = urlparse(url).netloc
    frag = pu.split(".")
    if len(frag) < 2:
        return ".".join(frag)
    else:
        co_domain = frag[-2] == "co" or frag[-2] == "com"
        # eth link redircts to ens lookup
        # https://eth.link/
        #  Similar to eth.link https://eth.limo/
        eth_link = frag[-2:] == ["eth", "link"] or frag[-2:] == ["eth", "limo"]
        return ".".join(frag[-3:] if co_domain or eth_link else frag[-2:])


def get_github_repo_url(github_url):
    if not github_url.startswith("http"):
        github_url = f"http://{github_url}"
    purl = urlparse(github_url)
    if purl.netloc == "github.com":
        psplit = purl.path.split("/")
        if len(psplit) >= 2:
            return purl._replace(path="/".join(psplit[:3])).geturl()
    else:
        return None


def open_localfile_with_pkgresource_fallback(path):
    if os.path.isfile(path):
        return open(path, "r")
    else:
        filename = os.path.basename(path)
        for res_dir in [conf, db]:
            if pkg_resources.is_resource(res_dir, filename):
                return pkg_resources.files(res_dir).joinpath(filename).open("r")

    raise Exception(f"File {path} was not found on disk or in package resources.")
