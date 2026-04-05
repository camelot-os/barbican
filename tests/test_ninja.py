# SPDX-FileCopyrightText: 2026 H2Lab
#
# SPDX-License-Identifier: Apache-2.0

import pytest
from pathlib import PureWindowsPath, PurePosixPath
from dataclasses import asdict

from camelot.barbican.builder.ninja import (
    NinjaWriter,
    NinjaRule,
    NinjaRuleDeps,
    NinjaVariable,
    NinjaBuild,
    NinjaFile,
    NinjaBuilderProtocol,
)


class TestNinjaWriter:

    escape_path_data = [
        (PurePosixPath("a b", "c:d"), "a$ b/c$:d"),
        (PureWindowsPath("C:/", "a b", "c d"), "C$:\\a$ b\\c$ d"),
    ]

    include_data = [
        str("path/to/other/build.ninja"),
        PurePosixPath("path", "to", "other", "build.ninja"),
        PureWindowsPath("path", "to", "other", "build.ninja"),
    ]

    def test_escape_basic(self):
        nw = NinjaWriter()
        assert nw._escape("a b") == "a$ b"
        assert nw._escape("a:b") == "a$:b"
        assert nw._escape("a$b") == "a$$b"

    @pytest.mark.parametrize("path,expected", escape_path_data, ids=["PosixPath", "WindowsPath"])
    def test_escape_path(self, path, expected):
        nw = NinjaWriter()
        assert nw._escape(path) == expected

    def test_wrap_no_wrap(self):
        nw = NinjaWriter(width=80)
        line = "short line"
        assert nw._wrap(line) == [line]

    def test_wrap_before_width(self):
        nw = NinjaWriter(width=20)
        line = "this is a simple line for wrapping"
        wrapped = nw._wrap(line)

        # The given line can be split in 2 lines that don't exceed max line width
        assert len(wrapped) == 2
        # wrapped line must be indented
        assert wrapped[1].startswith("  ")
        assert all(len(line) <= 20 for line in wrapped)

    def test_wrap_preserves_indent(self):
        nw = NinjaWriter(width=20)
        line = "  indented line that should wrap correctly"
        wrapped = nw._wrap(line)
        # wrapped line must be indented and preserves orig line indentation
        assert wrapped[1].startswith("    ")  # indent + 2

    def test_wrap_after_width(self):
        nw = NinjaWriter(width=20)
        s1 = "/very/long/path/file/name1"
        s2 = "/very/long/path/file/name2"
        s3 = "/very/long/path/file/name3"
        line = " ".join([s1, s2, s3])
        wrapped = nw._wrap(line)
        assert len(wrapped) == 3
        assert wrapped[0] == f"{s1} $"
        assert wrapped[1] == f"  {s2} $"
        assert wrapped[2] == f"  {s3}"

    def test_wrap_no_space_fallback(self):
        nw = NinjaWriter(width=10)
        line = "averyverylongwordwithoutspaces"
        wrapped = nw._wrap(line)

        # cannot wrap → stays as-is
        assert len(wrapped) == 1
        assert wrapped[0] == line

    def test_wrap_with_escaped_space(self):
        nw = NinjaWriter(width=20)
        # the space at pos == 20 is escaped, the line should be wrapped on the space before
        line = "this$ is$ a simple$ line$ with$ escaped$ space"
        wrapped = nw._wrap(line)

        # The given line can be split in 2 lines that don't exceed max line width
        assert len(wrapped) == 2
        # wrapped line must be indented
        assert wrapped[0] == "this$ is$ a $"
        assert wrapped[1] == "  simple$ line$ with$ escaped$ space"

    def test_wrap_with_escaped_escape_seq(self):
        nw = NinjaWriter(width=21)
        line = "this is a simple$$ line with escaped escape sequence"
        wrapped = nw._wrap(line)
        assert wrapped[0] == "this is a simple$$ $"

    def test_comment_wrap(self):
        nw = NinjaWriter(width=20)
        nw.comment("this is a long comment that should wrap nicely")
        # Comment are not wrapped using ninja escape sequence
        # Only check that each line starts with `# `
        assert all(line.startswith("# ") for line in nw.lines)
        assert all(len(line) <= 20 for line in nw.lines)

    def test_render_emtpy(self):
        nw = NinjaWriter()
        assert nw.render() == "\n"

    def test_render_output(self):
        nw = NinjaWriter()
        nw.variable("cc", "gcc")
        nw.newline()
        nw.comment("hello")
        out = nw.render()

        # Ensure that the render result is a string terminated w/ POSIX newline character
        assert isinstance(out, str)
        assert out.endswith("\n")

        # Verify content, must have the following 3 lines
        lines = out.splitlines()
        assert len(lines) == 3
        assert "cc = gcc" == lines[0]
        assert "" == lines[1]
        assert "# hello" == lines[2]

    def test_variable_str(self):
        nw = NinjaWriter()
        nw.variable("cc", "gcc")
        assert "cc = gcc\n" == nw.render()

    @pytest.mark.parametrize("PathType", [PurePosixPath, PureWindowsPath])
    def test_variable_path(self, PathType):
        nw = NinjaWriter()
        path = PathType("opt", "bin", "gcc")
        nw.variable("cc", path)
        expected = f"cc = {path}\n"
        assert expected == nw.render()

    def test_pool(self):
        nw = NinjaWriter()
        nw.pool("link_pool", 2)
        out = nw.render()
        lines = out.splitlines()
        assert "pool link_pool" == lines[0]
        assert "  depth = 2" == lines[1]

    @pytest.mark.parametrize("depth", [0, -1, -42])
    def test_pool_invalid(self, depth):
        nw = NinjaWriter()
        with pytest.raises(ValueError):
            nw.pool("bad", depth)

    def test_rule_basic(self):
        nw = NinjaWriter()
        nw.rule("cc", command="gcc -c $in -o $out", description="compile")
        out = nw.render()
        lines = out.splitlines()
        assert "rule cc" == lines[0]
        assert "  command = gcc -c $in -o $out" == lines[1]
        assert "  description = compile" == lines[2]

    @pytest.mark.parametrize("deps", [NinjaRuleDeps.GCC, NinjaRuleDeps.MSVC])
    def test_rule_enum(self, deps):
        nw = NinjaWriter()
        nw.rule("cc", command="gcc", deps=deps)
        out = nw.render()
        lines = out.splitlines()
        assert f"  deps = {deps}" == lines[2]

    def test_rule_bool_true(self):
        nw = NinjaWriter()
        nw.rule("cc", command="gcc", generator=True, restat=True)
        out = nw.render()
        lines = out.splitlines()
        assert "  generator = 1" == lines[2]
        assert "  restat = 1" == lines[3]

    def test_rule_bool_false(self):
        nw = NinjaWriter()
        nw.rule("cc", command="gcc", generator=False, restat=False)
        out = nw.render()
        assert "generator" not in out
        assert "restat" not in out

    def test_rule_invalid_key(self):
        nw = NinjaWriter()
        with pytest.raises(ValueError):
            nw.rule("bad", foo="bar")  # type: ignore

    def test_build_basic(self):
        nw = NinjaWriter()
        nw.build(outputs=["out"], rule="cc", inputs=["in.c"])
        out = nw.render()
        assert "build out: cc in.c" == out.splitlines()[0]

    def test_build_with_all_dependencies(self):
        nw = NinjaWriter()
        nw.build(
            outputs=["out"],
            rule="cc",
            inputs=["in.c"],
            implicit=["dep.h"],
            order_only=["order.txt"],
            validation=["val.txt"],
            implicit_outputs=["extra.o"],
        )

        out = nw.render()
        assert "build out | extra.o: cc in.c | dep.h || order.txt |@ val.txt" == out.splitlines()[0]

    def test_build_with_variables(self):
        nw = NinjaWriter()
        nw.build(
            outputs=["out"],
            rule="cc",
            variables={
                "flags": "-O2",
                "opts": "-Doption",
            },
        )

        lines = nw.render().splitlines()
        assert "  flags = -O2" == lines[1]
        assert "  opts = -Doption" == lines[2]

    def test_build_with_variables_list(self):
        nw = NinjaWriter()
        nw.build(
            outputs=["out"],
            rule="cc",
            variables={
                "opts": ["-O2", "-mcpu=cortex-m33", "-mfloat-abi=soft"],
            },
        )

        lines = nw.render().splitlines()
        assert "  opts = -O2 -mcpu=cortex-m33 -mfloat-abi=soft" == lines[1]

    @pytest.mark.parametrize("data", include_data, ids=["str", "PosixPath", "WindowsPath"])
    def test_include(self, data):
        nw = NinjaWriter()
        nw.include(data)
        assert nw.render().splitlines()[0] == f"include {data}"

    @pytest.mark.parametrize("data", include_data, ids=["str", "PosixPath", "WindowsPath"])
    def test_subninja(self, data):
        nw = NinjaWriter()
        nw.subninja(data)
        assert nw.render().splitlines()[0] == f"subninja {data}"


class EmptyBuilder(NinjaBuilderProtocol):
    def __init__(self, name: str):
        self._name: str = name

    @property
    def name(self) -> str:
        return self._name


class DummyBuilder(NinjaBuilderProtocol):
    def __init__(self, name: str):
        self._name: str = name

    @property
    def name(self) -> str:
        return self._name

    @classmethod
    def __ninja_variables__(cls):
        yield NinjaVariable(key="cc", value="gcc")

    @classmethod
    def __ninja_rules__(cls):
        yield NinjaRule(
            name="cc",
            command="gcc -c $in -o $out",
            description="compile",
        )

    def __ninja_builds__(self):
        yield NinjaBuild(
            outputs=["out.o"],
            rule="cc",
            inputs=["in.c"],
        )


class DummyBuilderImplicit:
    def __init__(self, name: str):
        self._name: str = name

    @property
    def name(self) -> str:
        return self._name

    @classmethod
    def __ninja_variables__(cls):
        yield NinjaVariable(key="cc", value="gcc")

    @classmethod
    def __ninja_rules__(cls):
        yield NinjaRule(
            name="cc",
            command="gcc -c $in -o $out",
            description="compile",
        )

    def __ninja_builds__(self):
        yield NinjaBuild(
            outputs=["out.o"],
            rule="cc",
            inputs=["in.c"],
        )


class TestNinjaFile:
    def test_ninja_file_empty(self):
        nf = NinjaFile([EmptyBuilder("empty")])
        lines = nf.generate().splitlines()
        # Should contain only comments and empty lines
        assert all(len(line) == 0 or line.startswith("# ") for line in lines)

    @pytest.mark.parametrize("Builder", [DummyBuilder, DummyBuilderImplicit])
    def test_ninja_file_generation(self, Builder):
        nf = NinjaFile([Builder("a")])
        content = nf.generate()

        assert "rule cc" in content
        assert "build out.o: cc in.c" in content
        assert "cc = gcc" in content

    @pytest.mark.parametrize("OtherBuilder", [EmptyBuilder, DummyBuilder, DummyBuilderImplicit])
    def test_ninja_file_duplicate_names(self, OtherBuilder):
        with pytest.raises(ValueError):
            NinjaFile([DummyBuilder("a"), OtherBuilder("a")])

    @pytest.mark.parametrize("Builder", [DummyBuilder, DummyBuilderImplicit])
    def test_ninja_file_multiple_types_dedup(self, Builder):
        class BuilderA(Builder):
            pass

        class BuilderB(Builder):
            pass

        class BuilderC(Builder):
            @classmethod
            def __ninja_rules__(cls):
                yield NinjaRule(
                    name="cc",
                    command="clang -c $in -o $out",
                    description="compile",
                )

        # rule should appear one (same rule from same base class)
        content = NinjaFile([BuilderA("a"), BuilderB("b")]).generate()
        assert content.count("rule cc") == 1

        # BuilderC overrides __ninja_rules__ with a rule name that already exists.
        with pytest.raises(ValueError):
            NinjaFile([BuilderA("a"), BuilderC("c")]).generate()

    def test_ninja_file_write(self, tmp_path_factory):
        f = tmp_path_factory.mktemp("generated") / "build.ninja"
        nf = NinjaFile([EmptyBuilder("empty")])
        nf.write(f)
        assert f.read_text(encoding="utf-8") == nf.generate()

    def test_ninja_build_dep(self):
        build1 = NinjaBuild(outputs=["output1"], rule="rule1")
        build2 = NinjaBuild(outputs=["output2"], rule="rule2", inputs=["input2", build1])
        nw = NinjaWriter()
        nw.build(**asdict(build2))
        assert nw.render().splitlines()[0] == "build output2: rule2 input2 output1"
