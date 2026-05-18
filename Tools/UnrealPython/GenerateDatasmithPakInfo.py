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


def _get_selected_folder_paths():
    selected_paths = []
    if hasattr(unreal.EditorUtilityLibrary, "get_selected_folder_paths"):
        selected_paths = unreal.EditorUtilityLibrary.get_selected_folder_paths() or []

    normalized_paths = []
    for path in selected_paths:
        normalized_path = _normalize_content_path(path)
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


if __name__ == "__main__":
    try:
        main()
    except Exception as exc:
        _error(str(exc))
        raise
