import json
import os
import shutil
import pypandoc

PANDOC_ENV_VAR = "PANDOC_PATH"


def ensure_pandoc_available() -> str:
    """Ensure a pandoc executable is available and return its path."""

    env_path = os.environ.get(PANDOC_ENV_VAR)
    if env_path:
        env_path = os.path.abspath(env_path)
        if os.path.isfile(env_path):
            bin_dir = os.path.dirname(env_path)
            os.environ["PATH"] = bin_dir + os.pathsep + os.environ.get("PATH", "")
            pypandoc.pandoc_path = env_path
            print(f"[OK] Pandoc detected via {PANDOC_ENV_VAR}: {env_path}")
            return env_path
        else:
            print(f"[WARN] {PANDOC_ENV_VAR} is set but points to a missing file: {env_path}")

    try:
        detected = pypandoc.get_pandoc_path()
        print(f"[OK] Pandoc detected: {detected}")
        return detected
    except OSError:
        pass

    which_path = shutil.which("pandoc")
    if which_path:
        pypandoc.pandoc_path = which_path
        print(f"[OK] Pandoc detected in PATH: {which_path}")
        return which_path

    raise RuntimeError(
        "Pandoc executable not found. Install Pandoc or set the PANDOC_PATH environment variable to its location."
    )


ensure_pandoc_available()

def generate_markdown_report(results_path: str, output_folder: str) -> str:
    """Convert fit_results.json into a Markdown report."""
    with open(results_path, "r", encoding="utf-8") as f:
        data = json.load(f)

    ts = data.get("timestamp", "")
    md = [f"# Plotinator Batch Report", f"**Date:** {ts}", "\n---\n"]

    for item in data.get("results", []):
        title = item["title"]
        formula = item["formula"]
        md.append(f"## {title}")
        md.append(f"**Formula:** `{formula}`  ")

        # Parameters table
        params = item.get("parameters", {})
        if params:
            md.append("**Parameters:**")
            md.append("| Name | Value | Error |")
            md.append("|------|-------:|------:|")
            for name, vals in params.items():
                md.append(f"| {name} | {vals['value']:.6g} | {vals['error']:.6g} |")
        else:
            md.append("_No parameters extracted._")

        # Metrics
        metrics = item.get("metrics")
        if metrics:
            md.append(
                f"\n**Residual Metrics:**  \n"
                f"Mean = {metrics['mean']:.4g} Std = {metrics['std']:.4g} RMSE = {metrics['rmse']:.4g}\n"
            )

        # Images
        plot_path = os.path.relpath(item["output_plot"], output_folder).replace("\\", "/")
        res_path = item.get("residuals_plot")
        md.append(f"![Plot]({plot_path})")
        if res_path:
            residuals_path = os.path.relpath(res_path, output_folder).replace("\\", "/")
            md.append(f"![Residuals]({residuals_path})")

        md.append("\n---\n")

    markdown_text = "\n".join(md)
    md_file = os.path.join(output_folder, "report.md")
    with open(md_file, "w", encoding="utf-8") as f:
        f.write(markdown_text)
    return md_file

def convert_to_pdf(md_path):
    md_path = os.path.abspath(md_path)
    pdf_path = md_path.replace(".md", ".pdf")

    # Move temporarily into the markdown folder to ensure image paths work
    cwd = os.getcwd()
    md_dir = os.path.dirname(md_path)
    os.chdir(md_dir)

    try:
        pypandoc.convert_text(
            open(md_path, "r", encoding="utf-8").read(),
            "pdf",
            format="md",
            outputfile=pdf_path,
            extra_args=["--pdf-engine=wkhtmltopdf", "--standalone"]
        )
        print(f"[OK] PDF exported successfully: {pdf_path}")
    except Exception as e:
        print(f"[ERROR] PDF generation failed: {e}")
    finally:
        os.chdir(cwd)

    return pdf_path


def main():
    base_folder = os.path.join("outputs", sorted(os.listdir("outputs"))[-1])
    json_path = os.path.join(base_folder, "fit_results.json")

    print(f"[RUN] Generating report from {json_path}...")
    md_path = generate_markdown_report(json_path, base_folder)
    print(f"[DONE] Markdown created: {md_path}")

    
    #print(f"[DEBUG]: Checking markdown path: {md_path}")
    #if not os.path.isfile(md_path):
    #   raise FileNotFoundError(f"Markdown file not found: {md_path}")

    pdf_path = convert_to_pdf(md_path)
    print(f"[SUCCESS] PDF exported: {pdf_path}")


if __name__ == "__main__":
    main()
