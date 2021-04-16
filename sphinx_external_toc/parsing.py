"""Parse the ToC to a `SiteMap` object."""
from collections.abc import Mapping
from pathlib import Path
from typing import Any, Dict, List, Optional, Sequence, Set, Tuple, Union

import attr
import yaml

from .api import Document, FileItem, GlobItem, SiteMap, TocTree, UrlItem

DEFAULT_SUBTREES_KEY = "subtrees"
DEFAULT_ITEMS_KEY = "sections"

FILE_KEY = "file"
GLOB_KEY = "glob"
URL_KEY = "url"

TOCTREE_OPTIONS = (
    "caption",
    "hidden",
    "maxdepth",
    "numbered",
    "reversed",
    "titlesonly",
)


class MalformedError(Exception):
    """Raised if toc file is malformed."""


def parse_toc_yaml(path: Union[str, Path], encoding: str = "utf8") -> SiteMap:
    """Parse the ToC file."""
    with Path(path).open(encoding=encoding) as handle:
        data = yaml.safe_load(handle)
    return parse_toc_data(data)


def parse_toc_data(data: Dict[str, Any]) -> SiteMap:
    """Parse a dictionary of the ToC."""
    if not isinstance(data, Mapping):
        raise MalformedError(f"toc is not a mapping: {type(data)}")

    defaults: Dict[str, Any] = data.get("defaults", {})

    doc_item, docs_list = _parse_doc_item(data, defaults, "/", file_key="root")

    site_map = SiteMap(root=doc_item, meta=data.get("meta"))

    _parse_docs_list(docs_list, site_map, defaults, "/")

    return site_map


def _parse_doc_item(
    data: Dict[str, Any],
    defaults: Dict[str, Any],
    path: str,
    *,
    subtrees_key: str = DEFAULT_SUBTREES_KEY,
    items_key: str = DEFAULT_ITEMS_KEY,
    file_key: str = FILE_KEY,
) -> Tuple[Document, Sequence[Dict[str, Any]]]:
    """Parse a single doc item."""
    if file_key not in data:
        raise MalformedError(f"'{file_key}' key not found: '{path}'")
    if items_key in data:
        # this is a shorthand for defining a single subtree
        if subtrees_key in data:
            raise MalformedError(
                f"Both '{subtrees_key}' and '{items_key}' found: '{path}'"
            )
        subtrees_data = [{items_key: data[items_key], **data.get("options", {})}]
    elif subtrees_key in data:
        subtrees_data = data[subtrees_key]
        if not (isinstance(subtrees_data, Sequence) and subtrees_data):
            raise MalformedError(f"'{subtrees_key}' not a non-empty list: '{path}'")
    else:
        subtrees_data = []

    _known_link_keys = {FILE_KEY, GLOB_KEY, URL_KEY}

    toctrees = []
    for toc_idx, toc_data in enumerate(subtrees_data):

        if not (isinstance(toc_data, Mapping) and items_key in toc_data):
            raise MalformedError(
                f"part not a mapping containing '{items_key}' key: '{path}{toc_idx}'"
            )

        items_data = toc_data[items_key]

        if not (isinstance(items_data, Sequence) and items_data):
            raise MalformedError(
                f"'{items_key}' not a non-empty list: '{path}{toc_idx}'"
            )

        # generate sections list
        items: List[Union[GlobItem, FileItem, UrlItem]] = []
        for item_idx, item_data in enumerate(items_data):

            if not isinstance(item_data, Mapping):
                raise MalformedError(
                    f"'{items_key}' item not a mapping type: '{path}{toc_idx}/{item_idx}'"
                )

            link_keys = _known_link_keys.intersection(item_data)

            # validation checks
            if not link_keys:
                raise MalformedError(
                    f"'{items_key}' item does not contain one of "
                    f"{_known_link_keys!r}: '{path}{toc_idx}/{item_idx}'"
                )
            if not len(link_keys) == 1:
                raise MalformedError(
                    f"'{items_key}' item contains incompatible keys "
                    f"{link_keys!r}: {path}{toc_idx}/{item_idx}"
                )
            for item_key in (GLOB_KEY, URL_KEY):
                for other_key in (subtrees_key, items_key):
                    if link_keys == {item_key} and other_key in item_data:
                        raise MalformedError(
                            f"'{items_key}' item contains incompatible keys "
                            f"'{item_key}' and '{other_key}': {path}{toc_idx}/{item_idx}"
                        )

            if link_keys == {FILE_KEY}:
                items.append(FileItem(item_data[FILE_KEY]))
            elif link_keys == {GLOB_KEY}:
                items.append(GlobItem(item_data[GLOB_KEY]))
            elif link_keys == {URL_KEY}:
                items.append(UrlItem(item_data[URL_KEY], item_data.get("title")))

        # generate toc key-word arguments
        keywords = {k: toc_data[k] for k in TOCTREE_OPTIONS if k in toc_data}
        for key in defaults:
            if key not in keywords:
                keywords[key] = defaults[key]

        try:
            toc_item = TocTree(items=items, **keywords)
        except TypeError as exc:
            raise MalformedError(f"toctree validation: {path}{toc_idx}") from exc
        toctrees.append(toc_item)

    try:
        doc_item = Document(
            docname=data[file_key], title=data.get("title"), subtrees=toctrees
        )
    except TypeError as exc:
        raise MalformedError(f"doc validation: {path}") from exc

    docs_data = [
        item_data
        for toc_data in subtrees_data
        for item_data in toc_data[items_key]
        if FILE_KEY in item_data
    ]

    return (
        doc_item,
        docs_data,
    )


def _parse_docs_list(
    docs_list: Sequence[Dict[str, Any]],
    site_map: SiteMap,
    defaults: Dict[str, Any],
    path: str,
):
    """Parse a list of docs."""
    for doc_data in docs_list:
        docname = doc_data["file"]
        if docname in site_map:
            raise MalformedError(f"document file used multiple times: {docname}")
        child_path = f"{path}{docname}/"
        child_item, child_docs_list = _parse_doc_item(doc_data, defaults, child_path)
        site_map[docname] = child_item

        _parse_docs_list(child_docs_list, site_map, defaults, child_path)


def create_toc_dict(site_map: SiteMap, *, skip_defaults: bool = True) -> Dict[str, Any]:
    """Create the Toc dictionary from a site-map."""
    data = _docitem_to_dict(
        site_map.root, site_map, skip_defaults=skip_defaults, file_key="root"
    )
    if site_map.meta:
        data["meta"] = site_map.meta.copy()
    return data


def _docitem_to_dict(
    doc_item: Document,
    site_map: SiteMap,
    *,
    skip_defaults: bool = True,
    subtrees_key: str = DEFAULT_SUBTREES_KEY,
    items_key: str = DEFAULT_ITEMS_KEY,
    file_key: str = FILE_KEY,
    parsed_docnames: Optional[Set[str]] = None,
) -> Dict[str, Any]:

    # protect against infinite recursion
    parsed_docnames = parsed_docnames or set()
    if doc_item.docname in parsed_docnames:
        raise RecursionError(f"{doc_item.docname!r} in site-map multiple times")
    parsed_docnames.add(doc_item.docname)

    data: Dict[str, Any] = {}

    data[file_key] = doc_item.docname
    if doc_item.title is not None:
        data["title"] = doc_item.title

    if not doc_item.subtrees:
        return data

    def _parse_item(item):
        if isinstance(item, FileItem):
            if item in site_map:
                return _docitem_to_dict(
                    site_map[item],
                    site_map,
                    skip_defaults=skip_defaults,
                    parsed_docnames=parsed_docnames,
                )
            return {FILE_KEY: str(item)}
        if isinstance(item, GlobItem):
            return {GLOB_KEY: str(item)}
        if isinstance(item, UrlItem):
            if item.title is not None:
                return {URL_KEY: item.url, "title": item.title}
            return {URL_KEY: item.url}
        raise TypeError(item)

    data[subtrees_key] = []
    fields = attr.fields_dict(TocTree)
    for toctree in doc_item.subtrees:
        # only add these keys if their value is not the default
        toctree_data = {
            key: getattr(toctree, key)
            for key in TOCTREE_OPTIONS
            if (not skip_defaults) or getattr(toctree, key) != fields[key].default
        }
        toctree_data[items_key] = [_parse_item(s) for s in toctree.items]
        data[subtrees_key].append(toctree_data)

    # apply shorthand if possible (one toctree in subtrees)
    if len(data[subtrees_key]) == 1 and items_key in data[subtrees_key][0]:
        old_toctree_data = data.pop(subtrees_key)[0]
        data[items_key] = old_toctree_data[items_key]
        # move options to options key
        if len(old_toctree_data) > 1:
            data["options"] = {
                k: v for k, v in old_toctree_data.items() if k != items_key
            }

    return data