import json
import os
import argparse
import re
import subprocess
import glob

def escape_typst(text):
    """
    Escapes Typst special characters: #, *, _, =, [, ], $, <, >
    """
    if not isinstance(text, str):
        return str(text)

    # We use a backslash to escape these characters
    # In Typst, \ acts as an escape character
    special_chars = r'([\\#*_=\[\]$<>])'
    return re.sub(special_chars, r'\\\1', text)

def parse_table(content):
    """
    Parses a pipe-delimited table string into Typst table format.
    """
    lines = [line.strip() for line in content.strip().split('\n') if line.strip()]
    if not lines:
        return ""

    # Filter out separator lines (e.g., |---|---|)
    rows = []
    for line in lines:
        if re.match(r'^\|?[\s\-\|:]+\|?$', line):
            continue
        # Split by pipe and clean up
        cells = [cell.strip() for cell in line.split('|')]
        # Remove empty first/last cells if they exist due to leading/trailing pipes
        if cells and not cells[0]:
            cells = cells[1:]
        if cells and not cells[-1]:
            cells = cells[:-1]
        if cells:
            rows.append(cells)

    if not rows:
        return ""

    num_columns = max(len(row) for row in rows)

    # Use a standard table without the unbreakable block wrapper so it breaks across pages naturally
    typst_table = f"#table(\n"
    typst_table += f"  columns: ({num_columns}),\n"
    typst_table += f"  inset: 10pt,\n"
    typst_table += f"  align: horizon,\n"

    for row in rows:
        # Pad row if it has fewer columns than max
        while len(row) < num_columns:
            row.append("")

        cells_str = ", ".join([f"[{escape_typst(cell)}]" for cell in row])
        typst_table += f"  {cells_str},\n"

    typst_table += ")"
    return typst_table

def build_book(input_dir, output_file):
    # Find all tagged_chunk_*.json files
    pattern = os.path.join(input_dir, "tagged_chunk_*.json")
    files = glob.glob(pattern)

    # Sort files by the numeric index in the filename
    def get_index(f):
        match = re.search(r'tagged_chunk_(\d+)\.json', f)
        return int(match.group(1)) if match else 0

    files.sort(key=get_index)

    with open(output_file, 'w', encoding='utf-8') as f:
        # 1. Write Template Header
        f.write('#set page(margin: (x: 2.5cm, y: 2.5cm), numbering: "1", header: align(right)[Manuscript])\n')
        f.write('#set text(font: "Linux Libertine", size: 10pt, leading: 0.65em)\n')
        f.write('#show heading: set block(above: 1.2em, below: 0.8em)\n\n')

        # 2. Iterate over chunks
        for file_path in files:
            try:
                with open(file_path, 'r', encoding='utf-8') as jf:
                    chunks = json.load(jf)

                if not isinstance(chunks, list):
                    chunks = [chunks]

                for chunk in chunks:
                    tag = chunk.get("tag", "body")
                    content = chunk.get("content", "")

                    if tag == "H1":
                        f.write(f"= {escape_typst(content)}\n\n")
                    elif tag == "H2":
                        f.write(f"== {escape_typst(content)}\n\n")
                    elif tag == "H3":
                        f.write(f"=== {escape_typst(content)}\n\n")
                    elif tag == "list":
                        escaped_content = escape_typst(content)
                        if not escaped_content.startswith("-"):
                            f.write(f"- {escaped_content}\n")
                        else:
                            f.write(f"{escaped_content}\n")
                    elif tag == "table":
                        f.write(f"{parse_table(content)}\n\n")
                    else: # Default to body
                        f.write(f"{escape_typst(content)}\n\n")
            except Exception as e:
                print(f"Error processing {file_path}: {e}")

def main():
    parser = argparse.ArgumentParser(description="Build a Typst book from tagged JSON chunks.")
    parser.add_argument("--input-dir", required=True, help="Directory containing tagged_chunk_XX.json files")
    parser.add_argument("--output", required=True, help="Path to the output .typ file")
    parser.add_argument("--compile", action="store_true", help="Attempt to compile the .typ file to PDF")

    args = parser.parse_args()

    input_dir = os.path.abspath(args.input_dir)
    output_file = os.path.abspath(args.output)

    if not os.path.isdir(input_dir):
        print(f"Error: Input directory {input_dir} does not exist.")
        return

    print(f"Building book from {input_dir} to {output_file}...")
    build_book(input_dir, output_file)
    print("Generation complete.")

    if args.compile:
        print(f"Compiling {output_file}...")
        try:
            # Check if typst is installed
            subprocess.run(["typst", "--version"], check=True, capture_output=True)
            subprocess.run(["typst", "compile", output_file], check=True)
            print(f"Successfully compiled to {os.path.splitext(output_file)[0]}.pdf")
        except FileNotFoundError:
            print("Error: 'typst' command not found. Please ensure Typst is installed and in your PATH.")
        except subprocess.CalledProcessError as e:
            print(f"Error during compilation: {e}")

if __name__ == "__main__":
    main()
