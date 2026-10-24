"""Reconstruct and test the current, frozen 3,748-comment public release."""
import os,subprocess,sys
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1]
ENV=os.environ.copy()
ENV.update(NHIS_DEPLOYMENT_MODE="hosted",NHIS_READ_ONLY="1",NHIS_PUBLIC_DEMO="1",
           NHIS_ALLOW_PUBLIC_PROVISIONAL="1",PYTHONDONTWRITEBYTECODE="1")
def run(*args):
    print("QC>", " ".join(args),flush=True)
    subprocess.run(args,cwd=ROOT,env=ENV,check=True)
if __name__=="__main__":
    if sys.version_info<(3,12):raise SystemExit("Python 3.12+ required")
    p=sys.executable
    run(p,"scripts/unpack_payload.py")
    run(p,"scripts/verify_public_release.py")
    for pat in ["test_v107_*.py","test_v108_*.py","test_v1082.py",
                "test_v109_*.py","test_v110_*.py","test_v111_*.py"]:
        run(p,"-m","unittest","discover","-v","-s","tests","-p",pat)
    print("CURRENT RELEASE QC PASS: 3,748 public records, all versioned suites")
