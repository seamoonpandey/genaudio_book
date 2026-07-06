import os
import sys
import tempfile
from pathlib import Path

_tmp = tempfile.mkdtemp(prefix="genaudi-test-")
os.environ["DATA_DIR"] = _tmp
os.environ["DEV_LOGIN"] = "1"
os.environ["WORKER_TOKEN"] = "test-worker-token"
os.environ["STRIPE_SECRET_KEY"] = "sk_test_x"
os.environ["STRIPE_WEBHOOK_SECRET"] = "whsec_test"
os.environ["STRIPE_PRICE_ID"] = "price_x"
os.environ.pop("BUCKET_NAME", None)
os.environ.pop("S3_BUCKET", None)

sys.path.insert(0, str(Path(__file__).resolve().parent))
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))
