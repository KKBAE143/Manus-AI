import os
import json
import time
import argparse
import logging
import urllib.request
import urllib.error
from pathlib import Path
from dotenv import load_dotenv

# Configure logging
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')
logger = logging.getLogger(__name__)

class CloudflarePool:
    def __init__(self):
        load_dotenv()
        self.credentials = []
        i = 1
        while True:
            account_id = os.getenv(f"CF_ACCOUNT_ID_{i}")
            api_token = os.getenv(f"CF_API_TOKEN_{i}")
            if not account_id or not api_token:
                # Try without index if i=1 and not found
                if i == 1:
                    account_id = os.getenv("CF_ACCOUNT_ID")
                    api_token = os.getenv("CF_API_TOKEN")
                    if account_id and api_token:
                        self.credentials.append((account_id, api_token))
                break
            self.credentials.append((account_id, api_token))
            i += 1

        if not self.credentials:
            raise ValueError("No Cloudflare credentials found in .env (CF_ACCOUNT_ID_N, CF_API_TOKEN_N)")

        self.current_index = 0
        logger.info(f"Initialized CloudflarePool with {len(self.credentials)} accounts.")

    def get_current(self):
        return self.credentials[self.current_index]

    def rotate(self):
        self.current_index = (self.current_index + 1) % len(self.credentials)
        account_id, _ = self.get_current()
        logger.info(f"Rotated to Cloudflare account: {account_id}")

def call_cloudflare_ai(account_id, api_token, text):
    model = "@cf/meta/llama-3-8b-instruct"
    url = f"https://api.cloudflare.com/client/v4/accounts/{account_id}/ai/run/{model}"

    system_prompt = "You are a semantic parser. Classify the structure of the provided text. Return ONLY a valid JSON array of objects. Each object must have a 'type' ('H1', 'H2', 'H3', 'body', 'table', 'list') and 'content' (the exact text). Do not rewrite, summarize, or drop a single word. Ensure your output is purely JSON."

    payload = {
        "messages": [
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": text}
        ]
    }

    data = json.dumps(payload).encode("utf-8")
    req = urllib.request.Request(url, data=data, method="POST")
    req.add_header("Authorization", f"Bearer {api_token}")
    req.add_header("Content-Type", "application/json")

    with urllib.request.urlopen(req, timeout=60) as response:
        res_data = json.loads(response.read().decode("utf-8"))
        if res_data.get("success"):
            return res_data["result"]["response"]
        else:
            raise Exception(f"Cloudflare API error: {res_data.get('errors')}")

def process_file(input_path, output_path, pool):
    logger.info(f"Processing {input_path} -> {output_path}")

    with open(input_path, 'r', encoding='utf-8') as f:
        data = json.load(f)

    # Assume data is a list of pages or a dict with pages
    # Based on prompt: "Read the text from each page in the input JSON"
    # We'll handle both list of dicts or a single dict with 'pages' key
    pages = data if isinstance(data, list) else data.get('pages', [])

    tagged_pages = []

    for i, page in enumerate(pages):
        text = page.get('text', '') if isinstance(page, dict) else str(page)
        if not text.strip():
            tagged_pages.append({"page": i, "content": []})
            continue

        retry_count = 0
        max_retries = 5
        success = False

        while not success and retry_count < max_retries:
            account_id, api_token = pool.get_current()
            try:
                logger.info(f"Tagging page {i} (attempt {retry_count + 1})...")
                ai_response = call_cloudflare_ai(account_id, api_token, text)

                # Attempt to parse JSON from response
                content_str = ai_response.strip()

                # Robust JSON extraction
                try:
                    # Try direct parse first
                    tagged_content = json.loads(content_str)
                except json.JSONDecodeError:
                    # Try finding the first [ and last ]
                    start = content_str.find("[")
                    end = content_str.rfind("]")
                    if start != -1 and end != -1:
                        try:
                            tagged_content = json.loads(content_str[start:end+1])
                        except json.JSONDecodeError:
                            raise Exception("Could not parse JSON from AI response even with extraction")
                    else:
                        raise Exception("AI response did not contain a JSON array")

                tagged_pages.append({"page": i, "content": tagged_content})
                success = True
            except urllib.error.HTTPError as e:
                if e.code == 429:
                    logger.warning(f"Rate limited (429) on account {account_id}. Rotating...")
                    pool.rotate()
                    time.sleep(2) # Brief pause
                else:
                    logger.error(f"HTTP Error {e.code}: {e.reason}")
                    retry_count += 1
                    time.sleep(1)
            except Exception as e:
                logger.error(f"Error processing page {i}: {str(e)}")
                retry_count += 1
                time.sleep(1)

        if not success:
            logger.error(f"Failed to process page {i} after {max_retries} retries.")
            tagged_pages.append({"page": i, "content": None, "error": "Failed after retries"})

    with open(output_path, 'w', encoding='utf-8') as f:
        json.dump(tagged_pages, f, indent=2, ensure_ascii=False)

def main():
    parser = argparse.ArgumentParser(description="Semantic Tagger using Cloudflare Workers AI")
    parser.add_argument("--input-dir", required=True, help="Directory containing chunk_XX.json files")
    parser.add_argument("--output-dir", required=True, help="Directory to save tagged_chunk_XX.json files")
    args = parser.parse_args()

    input_dir = Path(args.input_dir)
    output_dir = Path(args.output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)

    try:
        pool = CloudflarePool()
    except Exception as e:
        logger.error(str(e))
        return

    # Find all chunk_*.json files
    input_files = sorted(list(input_dir.glob("chunk_*.json")))

    if not input_files:
        logger.warning(f"No chunk_*.json files found in {input_dir}")
        return

    for input_file in input_files:
        output_file = output_dir / f"tagged_{input_file.name}"
        process_file(input_file, output_file, pool)

if __name__ == "__main__":
    main()
