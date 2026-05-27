"""CLI for memory module.

Usage:
    python3 -m memory add --name "..." --content "..." [--type project] [--description "..."]
    python3 -m memory add --name "..." --content-file path/to/file.md [--type project] [--description "..."]
    python3 -m memory search "query" [--max-results 5]
    python3 -m memory list
    python3 -m memory show "name"
"""

import argparse
import sys
from pathlib import Path

from memory.persistent import PersistentMemory


def cmd_add(args: argparse.Namespace) -> int:
    mem = PersistentMemory()
    content = args.content
    if args.content_file:
        content = Path(args.content_file).read_text(encoding="utf-8")
    path = mem.add(
        name=args.name,
        content=content,
        memory_type=args.type,
        description=args.description or "",
    )
    print(f"Memory saved: {path}")
    return 0


def cmd_search(args: argparse.Namespace) -> int:
    mem = PersistentMemory()
    results = mem.find_relevant(args.query, max_results=args.max_results)
    if not results:
        print("No memories found.")
        return 0
    for i, entry in enumerate(results, 1):
        print(f"{i}. [{entry.memory_type}] {entry.title}")
        if entry.description:
            print(f"   {entry.description}")
        preview = entry.body.replace("\n", " ")[:120]
        print(f"   {preview}...")
    return 0


def cmd_list(_args: argparse.Namespace) -> int:
    mem = PersistentMemory()
    entries = mem.list_entries()
    if not entries:
        print("No memories stored.")
        return 0
    for entry in entries:
        print(f"- [{entry.memory_type}] {entry.title} — {entry.description}")
    return 0


def cmd_show(args: argparse.Namespace) -> int:
    mem = PersistentMemory()
    entry = mem.find(args.name)
    if entry is None:
        print(f"Memory not found: {args.name}")
        return 1
    print(f"# {entry.title}")
    print(f"Type: {entry.memory_type}")
    print(f"Description: {entry.description}")
    print(f"Path: {entry.path}")
    print("---")
    print(entry.body)
    return 0


def main() -> int:
    parser = argparse.ArgumentParser(description="Quant Cluster memory CLI")
    subparsers = parser.add_subparsers(dest="command")

    # add
    add_parser = subparsers.add_parser("add", help="Add or update a memory")
    add_parser.add_argument("--name", required=True)
    add_parser.add_argument("--content", default="")
    add_parser.add_argument("--content-file", default=None, help="Read content from file")
    add_parser.add_argument("--type", default="project", choices=("user", "feedback", "project", "reference"))
    add_parser.add_argument("--description", default="")

    # search
    search_parser = subparsers.add_parser("search", help="Search memories by keyword")
    search_parser.add_argument("query")
    search_parser.add_argument("--max-results", type=int, default=5)

    # list
    subparsers.add_parser("list", help="List all memories")

    # show
    show_parser = subparsers.add_parser("show", help="Show a memory by name")
    show_parser.add_argument("name")

    args = parser.parse_args()
    if args.command == "add":
        return cmd_add(args)
    if args.command == "search":
        return cmd_search(args)
    if args.command == "list":
        return cmd_list(args)
    if args.command == "show":
        return cmd_show(args)

    parser.print_help()
    return 1


if __name__ == "__main__":
    sys.exit(main())
