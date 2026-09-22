#!/usr/bin/env bash
# Generate pydantic v2 models from the server's OpenAPI document (plan §8, WP4).
#
#   scripts/generate_models.sh [SOURCE] [OUTPUT]
#
# SOURCE  an openapi.json URL or a local file
#         (default: https://atb.uq.edu.au/api/v1/openapi.json)
# OUTPUT  default: src/atb_client/generated/models.py
#
# Needs datamodel-code-generator==0.26.5 (the `dev` extra; later releases cannot target
# Python 3.9). The version and flags are pinned so a regeneration against an unchanged schema is
# byte-identical: the CI contract job relies on that to diff against the checked-in file.
set -euo pipefail

SOURCE=${1:-https://atb.uq.edu.au/api/v1/openapi.json}
OUTPUT=${2:-src/atb_client/generated/models.py}

if [[ $SOURCE == http://* || $SOURCE == https://* ]]; then
    input=(--url "$SOURCE")
else
    input=(--input "$SOURCE")
fi

mkdir -p "$(dirname "$OUTPUT")"
datamodel-codegen \
    "${input[@]}" \
    --input-file-type openapi \
    --output-model-type pydantic_v2.BaseModel \
    --target-python-version 3.9 \
    --use-annotated \
    --field-constraints \
    --use-schema-description \
    --use-field-description \
    --enum-field-as-literal all \
    --collapse-root-models \
    --allow-extra-fields \
    --disable-timestamp \
    --output "$OUTPUT"

echo "wrote $OUTPUT from $SOURCE" >&2
