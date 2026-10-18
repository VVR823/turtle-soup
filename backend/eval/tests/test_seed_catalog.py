"""Owned static seed snapshots, never runtime/generated/feedback files."""
import pytest


IDS = ("shuangyu-yupei", "hotel", "xinren", "xin", "zhimengzhe", "seven-sins")


def test_selected_seed_catalog_is_explicit_versioned_and_full_proof():
    from app.baselines import strict_json
    from eval.catalog import build_seed_catalog, validate_catalog
    catalog = build_seed_catalog(soup_ids=IDS)
    assert {p.soupId for p in catalog} == set(IDS) and len(catalog) == 6
    assert validate_catalog(catalog) == catalog
    assert len({p.ruleSnapshot.ruleVersion for p in catalog}) == 1
    assert all(strict_json(p.ruleSnapshot.releaseManifestJson)["origin"] == "eval-seed-snapshot" for p in catalog)


@pytest.mark.parametrize("ids", [(), ("unknown",), ("xin", "xin"), ["xin"]])
def test_seed_catalog_refuses_empty_unknown_duplicate_or_coerced_selection(ids):
    from eval.catalog import build_seed_catalog
    from eval.contracts import DatasetError
    with pytest.raises(DatasetError): build_seed_catalog(soup_ids=ids)
