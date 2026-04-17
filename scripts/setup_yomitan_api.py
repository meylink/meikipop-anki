
import os
import io
import sys
import shutil
import zipfile
import requests
import subprocess

def setup_yomitan_api():
    # Define paths
    base_dir = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    target_dir = os.path.join(base_dir, "src", "yomitan-api")
    
    # 1. Create target directory
    if not os.path.exists(target_dir):
        os.makedirs(target_dir, exist_ok=True)
        print(f"Created directory: {target_dir}")
    
    # Check if already installed (simple check for key file)
    installer_path = os.path.join(target_dir, "install_yomitan_api.py")
    if os.path.exists(installer_path):
        print("Yomitan API files appear to be present.")
        # Ask user if they want to re-download
        choice = input("Redownload and overwrite? (y/N): ").lower()
        if choice != 'y':
            run_installer(target_dir)
            return

    # 2. Download from GitHub
    print("Downloading Yomitan API from GitHub...")
    url = "https://github.com/yomidevs/yomitan-api/archive/master.zip"
    try:
        r = requests.get(url)
        r.raise_for_status()
        z = zipfile.ZipFile(io.BytesIO(r.content))
        
        # 3. Extract
        # Zip contains a root folder "yomitan-api-master", we want contents in target_dir
        root_folder = z.namelist()[0].split('/')[0]
        
        print("Extracting...")
        z.extractall(os.path.join(base_dir, "src"))
        
        # Rename/Move to final location
        extracted_path = os.path.join(base_dir, "src", root_folder)
        
        # If target dir exists and we are overwriting, clear it first (except we just made it maybe)
        if os.path.exists(target_dir):
            shutil.rmtree(target_dir)
        
        os.rename(extracted_path, target_dir)
        print("Download complete.")
        
    except Exception as e:
        print(f"Error downloading/extracting: {e}")
        return

    # 4. Run the installer
    run_installer(target_dir)

def run_installer(cwd):
    print("\n" + "="*50)
    print("Launching Yomitan API interactive installer...")
    print("Please follow the prompts to register the Native Messaging Host.")
    print("="*50 + "\n")
    
    installer = "install_yomitan_api.py"
    if sys.platform.startswith('win'):
        subprocess.run(["python", installer], cwd=cwd, shell=True)
    else:
        subprocess.run([sys.executable, installer], cwd=cwd)

if __name__ == "__main__":
    setup_yomitan_api()
