"""Generate Datasmith pak metadata from the Unreal Editor Content Browser selection.

This script is intended to be executed by Unreal Editor Python. It depends on
Unreal Editor APIs and is not a standalone Python utility.
"""

import json
import os
from urllib.parse import urlparse

import unreal


PAK_URL_TEMPLATE = "http://192.168.50.11/paks/paks1000/pakchunk{chunk_id}-Windows.pak"
OUTPUT_RELATIVE_PATH = os.path.join("CustomData", "Pak", "DatasmithPakInfo.json")
MANUAL_PRIMARY_ASSET_LABEL_PATH = ""
DATASMITH_SCENE_CLASS_NAME = "DatasmithScene"
PRIMARY_ASSET_LABEL_CLASS_NAME = "PrimaryAssetLabel"
ROOT_ARRAY_KEY = "DatasmithLevels"


def _log(message):
    unreal.log("[GenerateDatasmithPakInfo] {0}".format(message))


def _warn(message):
    unreal.log_warning("[GenerateDatasmithPakInfo] {0}".format(message))


def _error(message):
    unreal.log_error("[GenerateDatasmithPakInfo] {0}".format(message))


def _as_string(value):
    if value is None:
        return ""
    return str(value)


def _class_name_from_asset_class_path(asset_class_path):
    """Return the short class name from an Unreal asset_class_path value."""
    if asset_class_path is None:
        return ""

    # In UE5 this is commonly an FTopLevelAssetPath with an asset_name property.
    if hasattr(asset_class_path, "get_editor_property"):
        asset_name = asset_class_path.get_editor_property("asset_name")
        if asset_name:
            return _as_string(asset_name)

    class_path_text = _as_string(asset_class_path)
    if "." in class_path_text:
        return class_path_text.rsplit(".", 1)[-1]
    if "/" in class_path_text:
        return class_path_text.rsplit("/", 1)[-1]
    return class_path_text


def _asset_data_class_name(asset_data):
    asset_class_path = asset_data.get_editor_property("asset_class_path")
    return _class_name_from_asset_class_path(asset_class_path)


def _asset_object_path(asset_data):
    package_name = _as_string(asset_data.get_editor_property("package_name"))
    asset_name = _as_string(asset_data.get_editor_property("asset_name"))
    if not package_name or not asset_name:
        return ""
    return "{0}.{1}".format(package_name, asset_name)


def _asset_package_path(asset_data):
    package_name = _as_string(asset_data.get_editor_property("package_name"))
    if "/" not in package_name:
        return ""
    return package_name.rsplit("/", 1)[0]


def _normalize_content_path(path):
    path_text = _as_string(path).strip()
    if not path_text:
        return ""

    # Selected/current Content Browser paths should already be folder paths. If an
    # object path is ever returned, strip the asset suffix before querying the
    # Asset Registry.
    if "." in path_text:
        path_text = path_text.split(".", 1)[0]
    return path_text.rstrip("/") or "/Game"


def _append_unique(items, item):
    if item and item not in items:
        items.append(item)


def _get_selected_folder_paths():
    selected_paths = []
    if hasattr(unreal.EditorUtilityLibrary, "get_selected_folder_paths"):
        selected_paths = unreal.EditorUtilityLibrary.get_selected_folder_paths() or []

    normalized_paths = []
    for path in selected_paths:
        normalized_path = _normalize_content_path(path)
        _append_unique(normalized_paths, normalized_path)
        if normalized_path:
            normalized_paths.append(normalized_path)
    return normalized_paths


def _get_current_content_browser_path():
    if hasattr(unreal.EditorUtilityLibrary, "get_current_content_browser_path"):
        current_path = unreal.EditorUtilityLibrary.get_current_content_browser_path()
        return _normalize_content_path(current_path)
    return ""


def _get_selected_asset_data():
    if hasattr(unreal.EditorUtilityLibrary, "get_selected_asset_data"):
        asset_data = list(unreal.EditorUtilityLibrary.get_selected_asset_data() or [])
        if asset_data:
            return asset_data

    selected_assets = list(unreal.EditorUtilityLibrary.get_selected_assets() or [])
    result = []
    for asset in selected_assets:
        asset_path = asset.get_path_name()
        data = unreal.EditorAssetLibrary.find_asset_data(asset_path)
        if data and data.is_valid():
            result.append(data)
    return result


def _log_selected_assets(selected_asset_data):
    _log("Selected asset count: {0}".format(len(selected_asset_data)))
def _get_required_primary_asset_label():
    selected_asset_data = _get_selected_asset_data()
    _log("Selected asset count: {0}".format(len(selected_asset_data)))

    for asset_data in selected_asset_data:
        _log(
            "Selected asset: {0} (class: {1})".format(
                _asset_object_path(asset_data),
                _asset_data_class_name(asset_data),
            )
        )


def _get_final_base_paths(selected_asset_data):
    selected_folder_paths = _get_selected_folder_paths()
    current_path = _get_current_content_browser_path()
    final_base_paths = []

    _log("Selected Content Browser folder paths: {0}".format(selected_folder_paths if selected_folder_paths else "<none>"))
    _log("Current Content Browser path: {0}".format(current_path if current_path else "<unavailable>"))

    for folder_path in selected_folder_paths:
        _append_unique(final_base_paths, folder_path)

    for asset_data in selected_asset_data:
        asset_folder_path = _asset_package_path(asset_data)
        if asset_folder_path:
            _log(
                "Selected asset contributes recursive base path: {0} from {1}".format(
                    asset_folder_path,
                    _asset_object_path(asset_data),
                )
            )
            _append_unique(final_base_paths, asset_folder_path)

    if not final_base_paths and current_path:
        _append_unique(final_base_paths, current_path)

    _log("Final base paths: {0}".format(final_base_paths if final_base_paths else "<none>"))
    return final_base_paths


def _load_asset_data_from_object_path(asset_path):
    normalized_path = _as_string(asset_path).strip()
    if not normalized_path:
        return None

    asset_data = unreal.EditorAssetLibrary.find_asset_data(normalized_path)
    if asset_data and asset_data.is_valid():
        return asset_data

    asset = unreal.EditorAssetLibrary.load_asset(normalized_path)
    if asset is None:
        return None

    loaded_asset_data = unreal.EditorAssetLibrary.find_asset_data(asset.get_path_name())
    if loaded_asset_data and loaded_asset_data.is_valid():
        return loaded_asset_data
    return None


def _selected_primary_asset_label(selected_asset_data):
    candidates = []
    for asset_data in selected_asset_data:
        if _asset_data_class_name(asset_data) == PRIMARY_ASSET_LABEL_CLASS_NAME:
            candidates.append(asset_data)

    if not candidates:
        return None

    for candidate in candidates:
        _log("PrimaryAssetLabel selected candidate: {0}".format(_asset_object_path(candidate)))

    if len(candidates) > 1:
        _warn(
            "Multiple selected PrimaryAssetLabel assets found; using the first selected candidate: {0}".format(
                _asset_object_path(candidates[0])
            )
        )

    _log("PrimaryAssetLabel resolution source: selected asset")
    return candidates[0]


def _manual_primary_asset_label():
    manual_path = _as_string(MANUAL_PRIMARY_ASSET_LABEL_PATH).strip()
    if not manual_path:
        return None

    _log("Trying manual PrimaryAssetLabel path: {0}".format(manual_path))
    asset_data = _load_asset_data_from_object_path(manual_path)
    if asset_data is None:
        _error("Manual PrimaryAssetLabel path could not be loaded: {0}".format(manual_path))
        return None

    class_name = _asset_data_class_name(asset_data)
    if class_name != PRIMARY_ASSET_LABEL_CLASS_NAME:
        _error(
            "Manual path is not a PrimaryAssetLabel: {0} (class: {1})".format(
                _asset_object_path(asset_data),
                class_name or "<unknown>",
            )
        )
        return None

    _log("PrimaryAssetLabel resolution source: manual path")
    return asset_data


def _path_segments(path):
    return [segment for segment in _normalize_content_path(path).split("/") if segment]


def _common_prefix_length(left_path, right_path):
    left_segments = _path_segments(left_path)
    right_segments = _path_segments(right_path)
    common = 0
    for left_segment, right_segment in zip(left_segments, right_segments):
        if left_segment != right_segment:
            break
        common += 1
    return common


def _primary_asset_label_sort_key(asset_data, first_base_path):
    candidate_folder = _asset_package_path(asset_data)
    normalized_base = _normalize_content_path(first_base_path)
    is_under_first_base = candidate_folder == normalized_base or candidate_folder.startswith(normalized_base + "/")

    if is_under_first_base:
        base_depth = len(_path_segments(normalized_base))
        candidate_depth = len(_path_segments(candidate_folder))
        return (0, candidate_depth - base_depth, _asset_object_path(asset_data))

    return (
        1,
        -_common_prefix_length(candidate_folder, normalized_base),
        len(_path_segments(candidate_folder)),
        _asset_object_path(asset_data),
    )


def _search_primary_asset_label(final_base_paths):
    if not final_base_paths:
        _warn("Cannot recursively search for PrimaryAssetLabel because there are no final base paths.")
        return None

    asset_registry = unreal.AssetRegistryHelpers.get_asset_registry()
    candidates_by_path = {}

    for base_path in final_base_paths:
        assets = list(asset_registry.get_assets_by_path(base_path, recursive=True, include_only_on_disk_assets=False) or [])
        _log("PrimaryAssetLabel recursive search asset count under {0}: {1}".format(base_path, len(assets)))
        for asset_data in assets:
            if _asset_data_class_name(asset_data) == PRIMARY_ASSET_LABEL_CLASS_NAME:
                candidates_by_path[_asset_object_path(asset_data)] = asset_data

    candidates = [candidates_by_path[path] for path in sorted(candidates_by_path)]
    if not candidates:
        _warn("No PrimaryAssetLabel assets found by recursive search.")
        return None

    _log("PrimaryAssetLabel recursive search candidate count: {0}".format(len(candidates)))
    for candidate in candidates:
        _log(
            "PrimaryAssetLabel recursive search candidate: {0} (package path: {1})".format(
                _asset_object_path(candidate),
                _asset_package_path(candidate),
            )
        )

    if len(candidates) == 1:
        _log("PrimaryAssetLabel resolution source: recursive search")
        return candidates[0]

    first_base_path = final_base_paths[0]
    chosen_candidate = sorted(candidates, key=lambda asset_data: _primary_asset_label_sort_key(asset_data, first_base_path))[0]
    _warn(
        "Multiple PrimaryAssetLabel assets found; chose closest candidate to first final base path {0}: {1}".format(
            first_base_path,
            _asset_object_path(chosen_candidate),
        )
    )
    _log("PrimaryAssetLabel resolution source: recursive search")
    return chosen_candidate


def _resolve_primary_asset_label(selected_asset_data, final_base_paths):
    selected_label = _selected_primary_asset_label(selected_asset_data)
    if selected_label is not None:
        return selected_label

    manual_label = _manual_primary_asset_label()
    if manual_label is not None:
        return manual_label

    search_label = _search_primary_asset_label(final_base_paths)
    if search_label is not None:
        return search_label

    _error(
        "Could not resolve a PrimaryAssetLabel. Select one, set MANUAL_PRIMARY_ASSET_LABEL_PATH, "
        "or place exactly one/closest PrimaryAssetLabel under the final base paths."
    )
    return None
    if len(selected_asset_data) != 1:
        raise RuntimeError(
            "Select exactly one PrimaryAssetLabel asset before running this script; found {0}.".format(
                len(selected_asset_data)
            )
        )

    label_asset_data = selected_asset_data[0]
    class_name = _asset_data_class_name(label_asset_data)
    if class_name != PRIMARY_ASSET_LABEL_CLASS_NAME:
        raise RuntimeError(
            "Selected asset must be PrimaryAssetLabel; found {0}.".format(class_name or "<unknown>")
        )

    label_asset = label_asset_data.get_asset()
    if label_asset is None:
        raise RuntimeError("Failed to load selected PrimaryAssetLabel asset.")
    return label_asset_data, label_asset


def _get_chunk_id(primary_asset_label):
    rules = primary_asset_label.get_editor_property("rules")
    if rules is None:
        _error("Resolved PrimaryAssetLabel has no rules property.")
        return None

    chunk_id = rules.get_editor_property("chunk_id")
    if chunk_id is None:
        _error("Resolved PrimaryAssetLabel.rules.chunk_id is not set.")
        return None

    try:
        chunk_id = int(chunk_id)
    except (TypeError, ValueError):
        _error("Resolved PrimaryAssetLabel.rules.chunk_id is not a valid integer: {0}.".format(chunk_id))
        return None

    if chunk_id < 0:
        _error("Resolved PrimaryAssetLabel.rules.chunk_id must be non-negative; found {0}.".format(chunk_id))
        return None
    return chunk_id


def _find_datasmith_scene_paths(base_content_paths):
    asset_registry = unreal.AssetRegistryHelpers.get_asset_registry()
    all_assets_by_path = {}
    datasmith_paths = []

    for base_content_path in base_content_paths:
        assets = list(asset_registry.get_assets_by_path(base_content_path, recursive=True, include_only_on_disk_assets=False) or [])
        _log("Recursive asset count under {0}: {1}".format(base_content_path, len(assets)))
        for asset_data in assets:
            object_path = _asset_object_path(asset_data)
            if object_path:
                all_assets_by_path[object_path] = asset_data

    for asset_data in all_assets_by_path.values():
        raise RuntimeError("Selected PrimaryAssetLabel has no rules property.")

    chunk_id = rules.get_editor_property("chunk_id")
    if chunk_id is None or int(chunk_id) < 0:
        raise RuntimeError("Selected PrimaryAssetLabel.rules.chunk_id must be set to a non-negative value.")
    return int(chunk_id)


def _get_base_content_path(label_asset_data):
    selected_paths = _get_selected_folder_paths()
    current_path = _get_current_content_browser_path()

    _log("Selected Content Browser paths: {0}".format(selected_paths if selected_paths else "<none>"))
    _log("Current Content Browser path: {0}".format(current_path if current_path else "<unavailable>"))

    if selected_paths:
        return selected_paths[0]
    if current_path:
        return current_path

    # Last-resort editor fallback: if only the PrimaryAssetLabel asset is selected,
    # search the folder containing that asset.
    package_name = _as_string(label_asset_data.get_editor_property("package_name"))
    package_path = package_name.rsplit("/", 1)[0] if "/" in package_name else ""
    if package_path:
        _warn("No selected/current Content Browser folder found; using selected label folder: {0}".format(package_path))
        return package_path

    raise RuntimeError("Could not determine a Content Browser base path.")


def _find_datasmith_scene_paths(base_content_path):
    asset_registry = unreal.AssetRegistryHelpers.get_asset_registry()
    all_assets = list(asset_registry.get_assets_by_path(base_content_path, recursive=True, include_only_on_disk_assets=False) or [])
    datasmith_paths = []

    for asset_data in all_assets:
        if _asset_data_class_name(asset_data) == DATASMITH_SCENE_CLASS_NAME:
            object_path = _asset_object_path(asset_data)
            if object_path:
                datasmith_paths.append(object_path)

    datasmith_paths = sorted(set(datasmith_paths))
    _log("Recursive asset count across final base paths: {0}".format(len(all_assets_by_path)))
    _log("DatasmithScene count across final base paths: {0}".format(len(datasmith_paths)))
    _log("Recursive asset count under {0}: {1}".format(base_content_path, len(all_assets)))
    _log("DatasmithScene count under {0}: {1}".format(base_content_path, len(datasmith_paths)))
    for datasmith_path in datasmith_paths:
        _log("DatasmithScene asset path: {0}".format(datasmith_path))
    return datasmith_paths


def _pak_filename_from_url(url):
    parsed_path = urlparse(_as_string(url)).path
    filename = os.path.basename(parsed_path)
    if filename:
        return filename
    return os.path.basename(_as_string(url))


def _load_existing_json(output_path):
    if not os.path.exists(output_path):
        return {ROOT_ARRAY_KEY: []}

    with open(output_path, "r", encoding="utf-8") as input_file:
        data = json.load(input_file)

    if not isinstance(data, dict):
        _warn("Existing JSON root was not an object; replacing it.")
        return {ROOT_ARRAY_KEY: []}

    levels = data.get(ROOT_ARRAY_KEY)
    if not isinstance(levels, list):
        _warn("Existing JSON did not contain a {0} array; recreating it.".format(ROOT_ARRAY_KEY))
        data[ROOT_ARRAY_KEY] = []
    return data


def _next_level_index(levels):
    max_index = -1
    for level in levels:
        if isinstance(level, dict):
            try:
                max_index = max(max_index, int(level.get("DatasmithLevelIndex", -1)))
            except (TypeError, ValueError):
                pass
    return max_index + 1


def _update_or_append_level(data, label_name, pak_url, datasmith_file_paths):
    levels = data.setdefault(ROOT_ARRAY_KEY, [])
    if not isinstance(levels, list):
        levels = []
        data[ROOT_ARRAY_KEY] = levels

    target_pak_filename = _pak_filename_from_url(pak_url)
    for level in levels:
        if not isinstance(level, dict):
            continue
        existing_pak_filename = _pak_filename_from_url(level.get("DatasmithPakFileUrl", ""))
        if existing_pak_filename == target_pak_filename:
            preserved_index = level.get("DatasmithLevelIndex", 0)
            level.update(
                {
                    "DatasmithLevelIndex": preserved_index,
                    "DatasmithLevel": label_name,
                    "DatasmithPakFileUrl": pak_url,
                    "DatasmithFilePaths": datasmith_file_paths,
                }
            )
            _log("JSON update mode: Updated existing item for pak filename: {0}".format(target_pak_filename))
            return "Updated", preserved_index
            _log("Updated existing DatasmithLevels item for pak filename: {0}".format(target_pak_filename))
            return "updated", preserved_index

    new_index = _next_level_index(levels)
    levels.append(
        {
            "DatasmithLevelIndex": new_index,
            "DatasmithLevel": label_name,
            "DatasmithPakFileUrl": pak_url,
            "DatasmithFilePaths": datasmith_file_paths,
        }
    )
    _log("JSON update mode: Appended new item for pak filename: {0}".format(target_pak_filename))
    return "Appended", new_index
    _log("Appended new DatasmithLevels item for pak filename: {0}".format(target_pak_filename))
    return "appended", new_index


def _save_json(data, output_path):
    output_dir = os.path.dirname(output_path)
    if not os.path.isdir(output_dir):
        os.makedirs(output_dir)

    with open(output_path, "w", encoding="utf-8") as output_file:
        json.dump(data, output_file, indent=4, ensure_ascii=False)
        output_file.write("\n")


def main():
    selected_asset_data = _get_selected_asset_data()
    _log_selected_assets(selected_asset_data)

    final_base_paths = _get_final_base_paths(selected_asset_data)
    if not final_base_paths:
        _error("No recursive search base path could be resolved from selected folders, selected assets, or current Content Browser path.")
        return False

    label_asset_data = _resolve_primary_asset_label(selected_asset_data, final_base_paths)
    if label_asset_data is None:
        return False

    primary_asset_label = label_asset_data.get_asset()
    if primary_asset_label is None:
        _error("Failed to load resolved PrimaryAssetLabel: {0}".format(_asset_object_path(label_asset_data)))
        return False

    label_name = _as_string(label_asset_data.get_editor_property("asset_name"))
    chunk_id = _get_chunk_id(primary_asset_label)
    if chunk_id is None:
        return False

    pak_url = PAK_URL_TEMPLATE.format(chunk_id=chunk_id)

    _log("Resolved PrimaryAssetLabel path: {0}".format(_asset_object_path(label_asset_data)))
    _log("Resolved ChunkID: {0}".format(chunk_id))
    _log("Datasmith pak URL: {0}".format(pak_url))

    datasmith_file_paths = _find_datasmith_scene_paths(final_base_paths)
    if not datasmith_file_paths:
        _warn("No DatasmithScene assets found under final base paths. JSON will still be updated.")
    label_asset_data, primary_asset_label = _get_required_primary_asset_label()
    label_name = _as_string(label_asset_data.get_editor_property("asset_name"))
    chunk_id = _get_chunk_id(primary_asset_label)
    pak_url = PAK_URL_TEMPLATE.format(chunk_id=chunk_id)
    base_content_path = _get_base_content_path(label_asset_data)

    _log("Using base content path: {0}".format(base_content_path))
    _log("PrimaryAssetLabel: {0}".format(_asset_object_path(label_asset_data)))
    _log("PrimaryAssetLabel.rules.chunk_id: {0}".format(chunk_id))
    _log("Datasmith pak URL: {0}".format(pak_url))

    datasmith_file_paths = _find_datasmith_scene_paths(base_content_path)
    if not datasmith_file_paths:
        _warn("No DatasmithScene assets found under {0}. JSON will still be updated.".format(base_content_path))

    project_root = unreal.Paths.project_dir()
    output_path = os.path.normpath(os.path.join(project_root, OUTPUT_RELATIVE_PATH))
    _log("Output JSON path: {0}".format(output_path))

    data = _load_existing_json(output_path)
    result, level_index = _update_or_append_level(data, label_name, pak_url, datasmith_file_paths)
    _save_json(data, output_path)

    _log("Finished {0} DatasmithPakInfo item at DatasmithLevelIndex {1}.".format(result, level_index))
    return True


if __name__ == "__main__":
    try:
        main()
    except Exception as exc:
        _error("Unexpected error while generating DatasmithPakInfo.json: {0}".format(exc))
        _error(str(exc))
        raise
