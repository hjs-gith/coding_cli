from coding_cli import skills as skills_mod


def write_skill(root, name, description, body="Do the thing."):
    d = root / "skills" / name
    d.mkdir(parents=True)
    (d / "SKILL.md").write_text(
        f"---\nname: {name}\ndescription: {description}\n---\n\n{body}\n"
    )
    return d


def test_discover_and_catalog(tmp_path):
    write_skill(tmp_path, "greeter", "say hello")
    found = skills_mod.discover_skills(tmp_path)
    assert "greeter" in found
    assert found["greeter"].description == "say hello"
    cat = skills_mod.catalog(found)
    assert ("greeter", "say hello") in cat


def test_loader_returns_body(tmp_path):
    write_skill(tmp_path, "greeter", "say hello", body="Step 1. Wave.")
    found = skills_mod.discover_skills(tmp_path)
    load = skills_mod.make_loader(found)
    out = load("greeter")
    assert "greeter" in out
    assert "Step 1. Wave." in out


def test_loader_unknown_name(tmp_path):
    found = skills_mod.discover_skills(tmp_path)
    load = skills_mod.make_loader(found)
    out = load("nope")
    assert out.startswith("ERROR")
    assert "unknown skill" in out


def test_frontmatter_missing_uses_dir_name(tmp_path):
    d = tmp_path / "skills" / "plain"
    d.mkdir(parents=True)
    (d / "SKILL.md").write_text("Just a body, no frontmatter.")
    found = skills_mod.discover_skills(tmp_path)
    assert "plain" in found
    assert found["plain"].body.startswith("Just a body")
