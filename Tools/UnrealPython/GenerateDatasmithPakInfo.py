import unreal
import os
import json
import datetime
import hashlib
import traceback


# ============================================================
# Settings
# ============================================================

LOG_PREFIX = "[GenerateDatasmithPakInfo]"

OUTPUT_JSON_FILE_NAME = "DatasmithPakInfo.json"
OUTPUT_RELATIVE_DIR = os.path.join("CustomData", "Pak")

PAK_BASE_URL = "http://192.168.50.11/paks/paks1000/"

DATASMITH_SCENE_CLASS_NAME = "DatasmithScene"
PRIMARY_ASSET_LABEL_CLASS_NAME = "PrimaryAssetLabel"

# 강제 검색 루트.
# 비워두면 Content Browser 선택/현재 위치 기준.
# 문자열 또는 배열 둘 다 가능.
# 예:
# MANUAL_ROOT_PATHS = "/Game/Pak100101"
# MANUAL_ROOT_PATHS = ["/Game/Pak100101", "/Game/Pak100205"]
MANUAL_ROOT_PATHS = ""

# 강제 PrimaryAssetLabel 경로.
# 비워두면 선택된 PrimaryAssetLabel 또는 검색 경로 내부에서 자동 탐색.
# 예:
# MANUAL_PRIMARY_ASSET_LABEL_PATH = "/Game/Pak100101/PAL_Pak100101.PAL_Pak100101"
MANUAL_PRIMARY_ASSET_LABEL_PATH = ""

# 비워두면 PrimaryAssetLabel 이름 사용.
DATASMITH_LEVEL_NAME_OVERRIDE = ""

# 동일 PakFileName 발견 시 DatasmithFilePaths 처리 방식.
# "replace": 현재 검색 결과로 완전히 교체
# "merge": 기존 목록 + 현재 검색 결과 합치기
UPDATE_FILE_PATHS_MODE = "replace"


# ============================================================
# Logging
# ============================================================

def _log(message):
    unreal.log("{0} {1}".format(LOG_PREFIX, message))


def _warn(message):
    unreal.log_warning("{0} {1}".format(LOG_PREFIX, message))


def _error(message):
    unreal.log_error("{0} {1}".format(LOG_PREFIX, message))


def _log_array(title, items):
    if items is None:
        _log("{0}: None".format(title))
        return

    _log("{0}: count={1}".format(title, len(items)))

    for item in items:
        _log("  {0}".format(item))


# ============================================================
# Common Helpers
# ============================================================

def _as_string(value):
    if value is None:
        return ""

    return str(value)


def _append_unique(items, item):
    if item is None:
        return

    if item == "":
        return

    if item not in items:
        items.append(item)


def _normalize_content_path(path):
    if not path:
        return ""

    path_text = _as_string(path).strip().replace("\\", "/")

    if not path_text:
        return ""

    # Content Browser virtual path 보정
    if path_text.startswith("/All/Game"):
        path_text = path_text.replace("/All/Game", "/Game", 1)

    # Object path가 들어온 경우:
    # /Game/Folder/Asset.Asset -> /Game/Folder/Asset
    last_segment = path_text.rsplit("/", 1)[-1]
    if "." in last_segment:
        path_text = path_text.split(".", 1)[0]

    path_text = path_text.rstrip("/")

    return path_text


def _flatten_content_paths(paths):
    result = []
    seen = set()

    def _add(value):
        if value is None:
            return

        if isinstance(value, (list, tuple, set)):
            for child in value:
                _add(child)
            return

        path_text = _normalize_content_path(value)

        if not path_text:
            return

        if not path_text.startswith("/"):
            return

        if path_text not in seen:
            seen.add(path_text)
            result.append(path_text)

    _add(paths)

    return result


def _get_project_dir():
    return unreal.Paths.project_dir()


def _get_output_dir():
    output_dir = os.path.join(_get_project_dir(), OUTPUT_RELATIVE_DIR)

    if not os.path.exists(output_dir):
        os.makedirs(output_dir)

    return output_dir


def _get_output_json_path():
    return os.path.join(_get_output_dir(), OUTPUT_JSON_FILE_NAME)


# ============================================================
# AssetData Helpers
# ============================================================

def _get_asset_class_name(asset_data):
    if not asset_data or not asset_data.is_valid():
        return ""

    try:
        class_path = asset_data.get_editor_property("asset_class_path")
    except Exception:
        return ""

    if not class_path:
        return ""

    try:
        return _as_string(class_path.get_editor_property("asset_name"))
    except Exception:
        pass

    try:
        return _as_string(class_path.asset_name)
    except Exception:
        pass

    class_path_text = _as_string(class_path)

    if DATASMITH_SCENE_CLASS_NAME in class_path_text:
        return DATASMITH_SCENE_CLASS_NAME

    if PRIMARY_ASSET_LABEL_CLASS_NAME in class_path_text:
        return PRIMARY_ASSET_LABEL_CLASS_NAME

    return class_path_text


def _is_asset_class(asset_data, expected_class_name):
    if not expected_class_name:
        return False

    return _get_asset_class_name(asset_data) == expected_class_name


def _asset_object_path(asset_data):
    if not asset_data or not asset_data.is_valid():
        return ""

    try:
        package_name = _as_string(asset_data.get_editor_property("package_name"))
        asset_name = _as_string(asset_data.get_editor_property("asset_name"))
    except Exception:
        return ""

    if not package_name or not asset_name:
        return ""

    return "{0}.{1}".format(package_name, asset_name)


def _asset_package_name(asset_data):
    if not asset_data or not asset_data.is_valid():
        return ""

    try:
        return _as_string(asset_data.get_editor_property("package_name"))
    except Exception:
        return ""


def _asset_package_path(asset_data):
    package_name = _asset_package_name(asset_data)

    if "/" not in package_name:
        return ""

    return package_name.rsplit("/", 1)[0]


def _asset_object_path_from_asset(asset):
    if not asset:
        return ""

    try:
        return _as_string(asset.get_path_name())
    except Exception:
        return ""


def _asset_folder_path_from_asset(asset):
    object_path = _asset_object_path_from_asset(asset)

    if not object_path:
        return ""

    package_path = object_path.split(".", 1)[0]

    if "/" not in package_path:
        return ""

    return _normalize_content_path(package_path.rsplit("/", 1)[0])


def _asset_class_name_from_asset(asset):
    if not asset:
        return ""

    try:
        return _as_string(asset.get_class().get_name())
    except Exception:
        return ""


# ============================================================
# Content Browser Selection
# ============================================================

def _get_selected_assets():
    try:
        assets = list(unreal.EditorUtilityLibrary.get_selected_assets() or [])
    except Exception as e:
        _warn("get_selected_assets failed: {0}".format(e))
        return []

    _log("Selected asset count: {0}".format(len(assets)))

    for asset in assets:
        _log(
            "Selected asset: {0} (class: {1})".format(
                _asset_object_path_from_asset(asset),
                _asset_class_name_from_asset(asset)
            )
        )

    return assets


def _get_selected_asset_folder_paths(selected_assets):
    result = []

    for asset in selected_assets:
        folder_path = _asset_folder_path_from_asset(asset)

        if not folder_path:
            continue

        _append_unique(result, folder_path)

        # 선택한 에셋이 /Game/Pak100101/Sub/Asset.Asset 구조라면,
        # /Game/Pak100101 루트도 후보에 추가한다.
        parts = folder_path.strip("/").split("/")

        if len(parts) >= 2 and parts[0] == "Game":
            top_folder = "/Game/{0}".format(parts[1])
            _append_unique(result, top_folder)

    return result


def _get_selected_folder_paths_from_content_browser():
    result = []

    try:
        path_view_paths = unreal.EditorUtilityLibrary.get_selected_path_view_folder_paths() or []
        for path in path_view_paths:
            _append_unique(result, _normalize_content_path(path))
    except Exception as e:
        _warn("get_selected_path_view_folder_paths failed: {0}".format(e))

    try:
        selected_folder_paths = unreal.EditorUtilityLibrary.get_selected_folder_paths() or []
        for path in selected_folder_paths:
            _append_unique(result, _normalize_content_path(path))
    except Exception as e:
        _warn("get_selected_folder_paths failed: {0}".format(e))

    return result


def _get_current_content_browser_path():
    try:
        return _normalize_content_path(
            unreal.EditorUtilityLibrary.get_current_content_browser_path()
        )
    except Exception as e:
        _warn("get_current_content_browser_path failed: {0}".format(e))
        return ""


def _get_final_base_paths(selected_assets):
    candidates = []

    if MANUAL_ROOT_PATHS:
        for path in _flatten_content_paths(MANUAL_ROOT_PATHS):
            _append_unique(candidates, path)

    selected_folder_paths = _get_selected_folder_paths_from_content_browser()
    selected_asset_folder_paths = _get_selected_asset_folder_paths(selected_assets)
    current_browser_path = _get_current_content_browser_path()

    _log_array("Content Browser selected folders", selected_folder_paths)
    _log_array("Selected asset folder paths", selected_asset_folder_paths)
    _log("Current Content Browser path: {0}".format(current_browser_path))

    for path in selected_folder_paths:
        _append_unique(candidates, path)

    if current_browser_path:
        _append_unique(candidates, current_browser_path)

    for path in selected_asset_folder_paths:
        _append_unique(candidates, path)

    final_paths = _flatten_content_paths(candidates)

    _log_array("Final base paths", final_paths)

    return final_paths


# ============================================================
# PrimaryAssetLabel Resolve
# ============================================================

def _is_primary_asset_label_object(asset):
    if not asset:
        return False

    try:
        if isinstance(asset, unreal.PrimaryAssetLabel):
            return True
    except Exception:
        pass

    return _asset_class_name_from_asset(asset) == PRIMARY_ASSET_LABEL_CLASS_NAME


def _load_asset_safe(asset_path):
    if not asset_path:
        return None

    candidates = []

    path_text = _as_string(asset_path).strip()

    if path_text:
        candidates.append(path_text)

    # /Game/Foo/Bar 형태면 /Game/Foo/Bar.Bar도 시도
    if path_text.startswith("/") and "." not in path_text.rsplit("/", 1)[-1]:
        asset_name = path_text.rsplit("/", 1)[-1]
        candidates.append("{0}.{1}".format(path_text, asset_name))

    for candidate in candidates:
        try:
            asset = unreal.EditorAssetLibrary.load_asset(candidate)
            if asset:
                return asset
        except Exception as e:
            _warn("load_asset failed: {0}, error: {1}".format(candidate, e))

    return None


def _get_selected_primary_asset_label(selected_assets):
    labels = []

    for asset in selected_assets:
        if _is_primary_asset_label_object(asset):
            labels.append(asset)

    if len(labels) <= 0:
        return None

    if len(labels) > 1:
        _warn("Multiple selected PrimaryAssetLabel assets. First one will be used.")

    _log("PrimaryAssetLabel resolved from selected asset.")
    return labels[0]


def _find_primary_asset_label_candidates(base_paths):
    asset_registry = unreal.AssetRegistryHelpers.get_asset_registry()
    final_paths = _flatten_content_paths(base_paths)

    candidates = []
    seen = set()

    if not final_paths:
        return candidates

    try:
        asset_registry.scan_paths_synchronous(final_paths, force_rescan=True)
        asset_registry.wait_for_completion()
    except Exception as e:
        _warn("AssetRegistry scan warning while finding PrimaryAssetLabel: {0}".format(e))

    for base_path in final_paths:
        try:
            asset_data_list = list(
                asset_registry.get_assets_by_path(
                    base_path,
                    recursive=True,
                    include_only_on_disk_assets=False
                ) or []
            )
        except Exception as e:
            _warn("get_assets_by_path failed while finding PrimaryAssetLabel. Path: {0}, Error: {1}".format(base_path, e))
            continue

        for asset_data in asset_data_list:
            if not asset_data or not asset_data.is_valid():
                continue

            if not _is_asset_class(asset_data, PRIMARY_ASSET_LABEL_CLASS_NAME):
                continue

            object_path = _asset_object_path(asset_data)

            if not object_path or object_path in seen:
                continue

            asset = _load_asset_safe(object_path)

            if not asset or not _is_primary_asset_label_object(asset):
                continue

            seen.add(object_path)
            candidates.append((asset_data, asset, object_path))

    return candidates


def _score_primary_asset_label_candidate(asset_data, first_base_path):
    package_path = _asset_package_path(asset_data)
    first_base_path = _normalize_content_path(first_base_path)

    if not package_path:
        return (999, 999999)

    if package_path == first_base_path:
        return (0, 0)

    if package_path.startswith(first_base_path + "/"):
        return (1, len(package_path) - len(first_base_path))

    if first_base_path.startswith(package_path + "/"):
        return (2, len(first_base_path) - len(package_path))

    return (3, len(package_path))


def _resolve_primary_asset_label(selected_assets, final_base_paths):
    selected_label = _get_selected_primary_asset_label(selected_assets)

    if selected_label:
        return selected_label, "selected asset"

    if MANUAL_PRIMARY_ASSET_LABEL_PATH:
        manual_label = _load_asset_safe(MANUAL_PRIMARY_ASSET_LABEL_PATH)

        if manual_label and _is_primary_asset_label_object(manual_label):
            _log("PrimaryAssetLabel resolved from MANUAL_PRIMARY_ASSET_LABEL_PATH.")
            return manual_label, "manual path"

        _error("MANUAL_PRIMARY_ASSET_LABEL_PATH is set but asset is not PrimaryAssetLabel: {0}".format(MANUAL_PRIMARY_ASSET_LABEL_PATH))
        return None, ""

    candidates = _find_primary_asset_label_candidates(final_base_paths)

    _log("PrimaryAssetLabel recursive candidate count: {0}".format(len(candidates)))

    for _, _, object_path in candidates:
        _log("  PrimaryAssetLabel candidate: {0}".format(object_path))

    if len(candidates) <= 0:
        _error("No PrimaryAssetLabel found. Select PrimaryAssetLabel, set MANUAL_PRIMARY_ASSET_LABEL_PATH, or put one under the search base path.")
        return None, ""

    if len(candidates) == 1:
        _log("PrimaryAssetLabel resolved from recursive search.")
        return candidates[0][1], "recursive search"

    first_base_path = final_base_paths[0] if final_base_paths else ""
    candidates.sort(key=lambda item: _score_primary_asset_label_candidate(item[0], first_base_path))

    _warn("Multiple PrimaryAssetLabels found. Closest candidate will be used.")
    _log("PrimaryAssetLabel resolved from recursive search by closest path.")

    return candidates[0][1], "recursive search closest"


def _get_chunk_id_from_primary_asset_label(primary_asset_label):
    if not primary_asset_label:
        return -1

    try:
        rules = primary_asset_label.get_editor_property("rules")
    except Exception as e:
        _error("Failed to get PrimaryAssetLabel.rules: {0}".format(e))
        return -1

    if not rules:
        _error("PrimaryAssetLabel.rules is None.")
        return -1

    try:
        return int(rules.get_editor_property("chunk_id"))
    except Exception as e:
        _error("Failed to get PrimaryAssetRules.chunk_id: {0}".format(e))
        return -1


def _get_datasmith_level_name(primary_asset_label):
    if DATASMITH_LEVEL_NAME_OVERRIDE:
        return DATASMITH_LEVEL_NAME_OVERRIDE

    if not primary_asset_label:
        return "DatasmithName"

    try:
        return _as_string(primary_asset_label.get_name())
    except Exception:
        return "DatasmithName"


# ============================================================
# DatasmithScene Recursive Search
# ============================================================

def _find_datasmith_scene_paths(base_content_paths):
    asset_registry = unreal.AssetRegistryHelpers.get_asset_registry()
    final_paths = _flatten_content_paths(base_content_paths)

    if not final_paths:
        _error("No valid base content paths for DatasmithScene search.")
        return []

    _log("DatasmithScene search base path count: {0}".format(len(final_paths)))

    for path in final_paths:
        _log("DatasmithScene search base path: {0}".format(path))

    try:
        asset_registry.scan_paths_synchronous(final_paths, force_rescan=True)
        asset_registry.wait_for_completion()
    except Exception as e:
        _warn("AssetRegistry scan warning: {0}".format(e))

    datasmith_paths = []
    seen = set()

    for base_content_path in final_paths:
        _log("Searching DatasmithScene under: {0}".format(base_content_path))

        try:
            all_assets = list(
                asset_registry.get_assets_by_path(
                    base_content_path,
                    recursive=True,
                    include_only_on_disk_assets=False
                ) or []
            )
        except Exception as e:
            _error("get_assets_by_path failed. BasePath: {0}, Error: {1}".format(base_content_path, e))
            continue

        _log("Recursive asset count under {0}: {1}".format(base_content_path, len(all_assets)))

        local_count = 0

        for asset_data in all_assets:
            if not asset_data or not asset_data.is_valid():
                continue

            if not _is_asset_class(asset_data, DATASMITH_SCENE_CLASS_NAME):
                continue

            object_path = _asset_object_path(asset_data)

            if not object_path:
                continue

            if object_path in seen:
                continue

            seen.add(object_path)
            datasmith_paths.append(object_path)
            local_count += 1

            _log("Found DatasmithScene: {0}".format(object_path))

        _log("DatasmithScene count under {0}: {1}".format(base_content_path, local_count))

    datasmith_paths = sorted(datasmith_paths)

    _log("Total DatasmithScene count: {0}".format(len(datasmith_paths)))

    return datasmith_paths


# ============================================================
# Pak File Metadata
# ============================================================

def _get_pak_file_name_from_chunk_id(chunk_id):
    return "pakchunk{0}-Windows.pak".format(chunk_id)


def _get_pak_url_from_pak_file_name(pak_file_name):
    return PAK_BASE_URL.rstrip("/") + "/" + pak_file_name


def _get_pak_file_name_from_url(pak_file_url):
    if not pak_file_url:
        return ""

    text = _as_string(pak_file_url).replace("\\", "/")

    text = text.split("?", 1)[0]
    text = text.split("#", 1)[0]

    return text.rsplit("/", 1)[-1]


def _get_local_pak_file_path(pak_file_name):
    return os.path.join(_get_output_dir(), pak_file_name)


def _get_file_last_modified_time_text(file_path):
    if not file_path or not os.path.exists(file_path):
        return ""

    timestamp = os.path.getmtime(file_path)
    dt = datetime.datetime.fromtimestamp(timestamp)

    return dt.strftime("%Y%m%dT%H%M%S")


def _get_file_sha1(file_path):
    if not file_path or not os.path.exists(file_path):
        return ""

    sha1 = hashlib.sha1()

    with open(file_path, "rb") as file:
        while True:
            chunk = file.read(1024 * 1024)

            if not chunk:
                break

            sha1.update(chunk)

    return sha1.hexdigest()


def _validate_pak_file_name_matches_url(level_item):
    pak_file_name = level_item.get("PakFileName", "")
    pak_file_url = level_item.get("DatasmithPakFileUrl", "")

    url_file_name = _get_pak_file_name_from_url(pak_file_url)

    if pak_file_name != url_file_name:
        _warn(
            "PakFileName and DatasmithPakFileUrl filename mismatch. "
            "PakFileName: {0}, UrlFileName: {1}".format(pak_file_name, url_file_name)
        )
        return False

    return True


# ============================================================
# JSON Helpers
# ============================================================

def _load_or_create_root_json(output_path):
    """
    return:
        (root_json, True)  : 정상 로드 또는 신규 생성 가능
        (None, False)      : 기존 JSON이 있지만 파싱 실패. 이 경우 저장 중단해야 함.
    """
    normalized_path = os.path.normpath(output_path)

    if not os.path.exists(normalized_path):
        _log("Existing JSON not found. New JSON root will be created: {0}".format(normalized_path))
        return {
            "DatasmithLevels": []
        }, True

    try:
        with open(normalized_path, "r", encoding="utf-8") as file:
            root_json = json.load(file)

    except json.JSONDecodeError as e:
        _error("Existing JSON file is invalid. Save aborted.")
        _error("Path: {0}".format(normalized_path))
        _error("JSON error: line {0}, column {1}, message: {2}".format(e.lineno, e.colno, e.msg))
        _error("Please fix the JSON syntax first. The script will not overwrite or recreate this file.")
        return None, False

    except Exception as e:
        _error("Failed to read existing JSON. Save aborted.")
        _error("Path: {0}".format(normalized_path))
        _error("Error: {0}".format(e))
        return None, False

    # 과거에 배열 루트로 저장한 경우 보정
    if isinstance(root_json, list):
        _warn("Existing JSON root is array. It will be converted to object root with DatasmithLevels.")
        return {
            "DatasmithLevels": root_json
        }, True

    if not isinstance(root_json, dict):
        _error("Existing JSON root is not object. Save aborted.")
        _error("Path: {0}".format(normalized_path))
        return None, False

    if "DatasmithLevels" not in root_json:
        _warn("Existing JSON has no DatasmithLevels field. It will be created.")
        root_json["DatasmithLevels"] = []

    if not isinstance(root_json["DatasmithLevels"], list):
        _error("Existing DatasmithLevels is not array. Save aborted.")
        _error("Path: {0}".format(normalized_path))
        return None, False

    return root_json, True


def _get_next_datasmith_level_index(root_json):
    levels = root_json.get("DatasmithLevels", [])
    max_index = -1

    for item in levels:
        if not isinstance(item, dict):
            continue

        try:
            index = int(item.get("DatasmithLevelIndex", -1))
        except Exception:
            continue

        if index > max_index:
            max_index = index

    return max_index + 1


def _get_existing_item_pak_file_name(item):
    if not isinstance(item, dict):
        return ""

    pak_file_name = _as_string(item.get("PakFileName", ""))

    if pak_file_name:
        return pak_file_name

    return _get_pak_file_name_from_url(item.get("DatasmithPakFileUrl", ""))


def _find_existing_level_array_index_by_pak_file_name(root_json, pak_file_name):
    if not pak_file_name:
        return -1

    levels = root_json.get("DatasmithLevels", [])

    for index, item in enumerate(levels):
        existing_pak_file_name = _get_existing_item_pak_file_name(item)

        if existing_pak_file_name == pak_file_name:
            return index

    return -1


def _merge_file_paths_unique(existing_paths, incoming_paths):
    result = []
    seen = set()

    if not isinstance(existing_paths, list):
        existing_paths = []

    if not isinstance(incoming_paths, list):
        incoming_paths = []

    for path in existing_paths:
        if not isinstance(path, str):
            continue

        if path not in seen:
            seen.add(path)
            result.append(path)

    for path in incoming_paths:
        if not isinstance(path, str):
            continue

        if path not in seen:
            seen.add(path)
            result.append(path)

    return result


def _build_datasmith_level_item(primary_asset_label, chunk_id, datasmith_file_paths, datasmith_level_index):
    pak_file_name = _get_pak_file_name_from_chunk_id(chunk_id)
    pak_file_url = _get_pak_url_from_pak_file_name(pak_file_name)
    local_pak_file_path = _get_local_pak_file_path(pak_file_name)

    pak_last_modified_time = ""
    pak_file_hash_sha1 = ""

    if os.path.exists(local_pak_file_path):
        pak_last_modified_time = _get_file_last_modified_time_text(local_pak_file_path)
        pak_file_hash_sha1 = _get_file_sha1(local_pak_file_path)
    else:
        _warn("Local pak file not found. Pak metadata will be empty: {0}".format(local_pak_file_path))

    level_item = {
        "DatasmithLevelIndex": datasmith_level_index,
        "DatasmithLevel": _get_datasmith_level_name(primary_asset_label),
        "DatasmithPakFileUrl": pak_file_url,
        "PakFileName": pak_file_name,
        "PakLastModifiedTime": pak_last_modified_time,
        "PakFileHashSha1": pak_file_hash_sha1,
        "DatasmithFilePaths": datasmith_file_paths
    }

    _validate_pak_file_name_matches_url(level_item)

    _log("PakFileName: {0}".format(pak_file_name))
    _log("Local pak file path: {0}".format(local_pak_file_path))
    _log("PakLastModifiedTime: {0}".format(pak_last_modified_time))
    _log("PakFileHashSha1: {0}".format(pak_file_hash_sha1))

    return level_item


def _update_or_append_and_save_json(level_item):
    output_path = os.path.normpath(_get_output_json_path())

    root_json, load_success = _load_or_create_root_json(output_path)

    if not load_success or root_json is None:
        _error("Update or append canceled because existing JSON could not be loaded safely.")
        return "", "Failed", -1

    incoming_pak_file_name = _as_string(level_item.get("PakFileName", ""))

    if not incoming_pak_file_name:
        incoming_pak_file_name = _get_pak_file_name_from_url(level_item.get("DatasmithPakFileUrl", ""))

    if not incoming_pak_file_name:
        _error("Invalid level item. PakFileName is empty.")
        return "", "Failed", -1

    existing_index = _find_existing_level_array_index_by_pak_file_name(
        root_json,
        incoming_pak_file_name
    )

    if existing_index >= 0:
        existing_item = root_json["DatasmithLevels"][existing_index]
        existing_level_index = existing_item.get("DatasmithLevelIndex", existing_index)

        try:
            existing_level_index = int(existing_level_index)
        except Exception:
            existing_level_index = existing_index

        level_item["DatasmithLevelIndex"] = existing_level_index

        if UPDATE_FILE_PATHS_MODE == "merge":
            level_item["DatasmithFilePaths"] = _merge_file_paths_unique(
                existing_item.get("DatasmithFilePaths", []),
                level_item.get("DatasmithFilePaths", [])
            )

        root_json["DatasmithLevels"][existing_index] = level_item
        result_mode = "Updated"

        _log("Existing item found by PakFileName. Update item.")
        _log("PakFileName: {0}".format(incoming_pak_file_name))
        _log("ArrayIndex: {0}".format(existing_index))
        _log("DatasmithLevelIndex preserved: {0}".format(existing_level_index))

    else:
        next_index = _get_next_datasmith_level_index(root_json)
        level_item["DatasmithLevelIndex"] = next_index

        root_json["DatasmithLevels"].append(level_item)
        result_mode = "Appended"

        _log("No existing item found. Append new item.")
        _log("PakFileName: {0}".format(incoming_pak_file_name))
        _log("DatasmithLevelIndex: {0}".format(next_index))

    try:
        output_dir = os.path.dirname(output_path)

        if not os.path.exists(output_dir):
            os.makedirs(output_dir)

        # 원자적 저장에 가까운 방식.
        # 먼저 tmp에 저장 후 replace.
        temp_output_path = output_path + ".tmp"

        with open(temp_output_path, "w", encoding="utf-8") as file:
            json.dump(root_json, file, ensure_ascii=False, indent=4)

        os.replace(temp_output_path, output_path)

    except Exception as e:
        _error("Failed to save JSON: {0}, Error: {1}".format(output_path, e))
        return "", "Failed", -1

    final_index = level_item.get("DatasmithLevelIndex", -1)

    _log("Saved JSON path: {0}".format(output_path))
    _log("JSON update mode: {0}".format(result_mode))
    _log("DatasmithLevels count: {0}".format(len(root_json.get("DatasmithLevels", []))))

    return output_path, result_mode, final_index


# ============================================================
# Main
# ============================================================

def main():
    try:
        selected_assets = _get_selected_assets()

        final_base_paths = _get_final_base_paths(selected_assets)

        if not final_base_paths:
            _error("No valid base path found. Select a Content Browser folder, select an asset, or set MANUAL_ROOT_PATHS.")
            return

        primary_asset_label, label_source = _resolve_primary_asset_label(
            selected_assets,
            final_base_paths
        )

        if not primary_asset_label:
            return

        _log("PrimaryAssetLabel resolution source: {0}".format(label_source))
        _log("Resolved PrimaryAssetLabel path: {0}".format(_asset_object_path_from_asset(primary_asset_label)))

        chunk_id = _get_chunk_id_from_primary_asset_label(primary_asset_label)

        if chunk_id < 0:
            _error("Invalid ChunkID. PrimaryAssetLabel.rules.chunk_id is probably -1.")
            return

        _log("Resolved ChunkID: {0}".format(chunk_id))

        datasmith_file_paths = _find_datasmith_scene_paths(final_base_paths)

        if len(datasmith_file_paths) <= 0:
            _warn("No DatasmithScene assets found.")

        level_item = _build_datasmith_level_item(
            primary_asset_label=primary_asset_label,
            chunk_id=chunk_id,
            datasmith_file_paths=datasmith_file_paths,
            datasmith_level_index=-1
        )

        saved_path, result_mode, final_level_index = _update_or_append_and_save_json(level_item)

        _log("{0} DatasmithLevel Item:".format(result_mode))
        _log(json.dumps(level_item, ensure_ascii=False, indent=4))

        if saved_path:
            unreal.SystemLibrary.print_string(
                None,
                "{0} DatasmithLevel\nIndex: {1}\nChunkID: {2}\nDatasmithScene Count: {3}\n{4}".format(
                    result_mode,
                    final_level_index,
                    chunk_id,
                    len(datasmith_file_paths),
                    saved_path
                ),
                text_color=unreal.LinearColor(0.0, 1.0, 0.2, 1.0),
                duration=6.0
            )

    except Exception as e:
        _error("Unexpected error while generating DatasmithPakInfo.json: {0}".format(e))
        _error(traceback.format_exc())


main()