# CLI reference

The API key is never accepted on the command line: it comes from `ATB_API_KEY` or a
config-file profile (`--profile`). Global options `--profile`, `--base-url`, `--table` may
appear before or after the subcommand.

| command | does |
|---|---|
| `atb get MOLID` | print a molecule's metadata |
| `atb status MOLID` | poll a molecule once; exit 0 done, 4 running, 5 failed |
| `atb submit FILE --charge N [--public\|--private] [--ref REF] [--format FMT] [--max-qm-level N] [--moltype T] [--wait]` | submit a structure; a duplicate adopts the existing entry |
| `atb submit-batch FILE [--charge-field F] [--ref-field F] [--charge N] [--public\|--private]` | submit up to 100 structures from an SDF |
| `atb download MOLID NAMES... [-o DIR] [--hash H] [--ff FF]` | download named files of one molecule |
| `atb remap MOLID FILE [--format FMT] [--mode MODE] [--names query\|reference] [--coords query\|reference] [--outputs ...] [--united] [-o PATH]` | this molecule's outputs in your structure's atom order |
| `atb bundle NAMES... [--molids IDS \| --molids-from FILE] [-o DIR]` | download files of many molecules as one bundle |
| `atb search [--inchi-key K] [--inchi I] [--smiles S] [--common-name N] [--formula F] [--q TEXT] [--filter KEY=VALUE] [--limit N] [--all]` | search molecules |
| `atb ifp FF [--format gxx\|g96] [-o FILE]` | a force field's interaction parameter file |
| `atb keys create [--name N] [--scopes S,S] [--expires N[d]]` | mint an API key (shown once) |
| `atb keys list` | list your API keys |
| `atb keys revoke ID` | revoke an API key |
| `atb usage` | today's request counters and limits |
| `atb admin users [Q] [--limit N] [--all]` | list accounts (needs `admin` scope) |
| `atb admin molecule MOLID [--max-qm-level N] [--curation-trust N] [--tag-add T] [--tag-remove T]` | curate one molecule |
| `atb admin stalled [--scan N] [--all]` | molecules no QM driver will pick up |
| `atb admin audit [--key-id N] [--principal P] [--user-email E] [--target-type T] [--target-id I] [--outcome O] [--limit N] [--all]` | recent admin/service/root writes and denials |

Run `atb --help` or `atb <command> --help` for the full flag list; the table above mirrors
`atb_client.cli.build_parser`.
