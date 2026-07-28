import sys
import os
import subprocess

def main():
    host = sys.argv[1] if len(sys.argv) > 1 else "ubuntu@161.118.190.49"
    key_path = sys.argv[2] if len(sys.argv) > 2 else r"C:\Users\user\ssh\ssh-key-2026-07-22.key"
    dest = "/srv/prepwithtee"

    repo_root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    os.chdir(repo_root)

    print(f"==> Packaging and shipping app to {host}:{dest} ...")
    print("Files: deploy, pipeline, website, taxonomy, data/raw, data/index.db, requirements.txt")

    # Use native Windows tar + ssh to stream tarball directly to remote server
    tar_cmd = (
        f'tar --exclude="__pycache__" --exclude="*.pyc" '
        f'-czf - deploy pipeline website taxonomy requirements.txt CLAUDE.md data/raw data/index.db | '
        f'ssh -i "{key_path}" {host} "tar -xzf - -C {dest}"'
    )

    res = subprocess.run(tar_cmd, shell=True)
    if res.returncode == 0:
        print("\n[OK] Upload complete!")
        print("\nNext steps on server:")
        print("    sudo systemctl restart prepwithtee")
        print("    curl -s localhost:8017/api/health")
    else:
        print(f"\n[ERROR] Upload failed with exit code {res.returncode}")

if __name__ == "__main__":
    main()
