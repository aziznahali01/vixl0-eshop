import os
import re
import unicodedata

def clean_filename(filename):
    # Normalize unicode (é → e, weird chars → base)
    filename = unicodedata.normalize("NFKD", filename)

    # Replace problematic dashes
    filename = filename.replace("—", "-").replace("–", "-")

    name, ext = os.path.splitext(filename)

    # Remove emojis & symbols
    name = re.sub(r'[\U00010000-\U0010ffff]', '', name)

    # Remove illegal Windows / ZIP characters
    name = re.sub(r'[<>:"/\\|?*\x00-\x1F]', '', name)

    # Keep only safe characters
    name = re.sub(r'[^A-Za-z0-9 ._-]', '', name)

    # Cleanup spaces
    name = re.sub(r'\s+', ' ', name).strip()

    return name + ext


def clean_folder(folder_path):
    for filename in os.listdir(folder_path):
        old_path = os.path.join(folder_path, filename)

        if not os.path.isfile(old_path):
            continue

        new_name = clean_filename(filename)
        new_path = os.path.join(folder_path, new_name)

        if new_name != filename:
            print(f"Renaming: {filename} → {new_name}")
            os.rename(old_path, new_path)


if __name__ == "__main__":
    folder = input("Enter folder path: ").strip('"')
    clean_folder(folder)
    print("Done.")
