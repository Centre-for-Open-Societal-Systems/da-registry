# openg2p-registry-da-extension

Extension package for the OpenG2P registry platform that implements the
Development Agent (DA) register. Selected at runtime with
`REGISTRY_EXTENSION_MODULE=openg2p_registry_da_extension`.

| Register | Table | Base classes |
|---|---|---|
| `DA` | `g2p_register_das` | `G2PRegister`, `G2PPerson`, `G2PGeo` |

- `register_domain/models/da.py`: the DA columns on top of the platform's person and geo columns.
- `register_domain/services/g2p_register_domain_service_da.py`: validation (names, Fayda FIN, mobile, dates), flattened posting names, search text and record name.
- `register_domain/id_generator/`: `DA-` prefix for functional IDs.
- `meta_data/`: register definition, schemas, portal sections and intake form, code lists, AWE mapping, DCI output template registration.
- `awe_meta_data/`: approval policy for DA intake and change requests.
- `templates/openg2p_da_to_dci.json.j2`: DCI search output read by the Frappe DA Service.
