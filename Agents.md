# AGENTS.md

## Project Context

This is an Unreal Engine 5.6 project.

The Python script under `Tools/UnrealPython/GenerateDatasmithPakInfo.py` is intended to run inside the Unreal Editor Python environment, not as standalone system Python.

## Important Unreal Python Constraints

- Use `unreal.EditorUtilityLibrary` for Content Browser selected paths and selected assets.
- Use `unreal.AssetRegistryHelpers.get_asset_registry()` for recursive asset search.
- Use `asset_data.get_editor_property("asset_class_path")`, not deprecated `asset_class`.
- Target asset class name is `DatasmithScene`.
- Selected asset must be `PrimaryAssetLabel`.
- Read `PrimaryAssetLabel.rules.chunk_id`.
- Generate pak URL as:
  `http://192.168.50.11/paks/paks1000/pakchunk{ChunkID}-Windows.pak`

## JSON Output

Save to:

`<ProjectRoot>/CustomData/Pak/DatasmithPakInfo.json`

Root format:

```json
{
    "DatasmithLevels": []
}