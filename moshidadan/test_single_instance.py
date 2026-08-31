"""单实例互斥单元测试。"""
import subprocess
import sys
import time
import unittest
import uuid

import single_instance


class SingleInstanceTest(unittest.TestCase):
    """覆盖: 第二个实例被拒绝 / 第一个实例退出后可以再次获取。"""

    def test_second_instance_cannot_acquire_while_first_running(self):
        name = "Local\\TestMoshidadan_" + uuid.uuid4().hex
        code = (
            "import single_instance, time;"
            "h = single_instance.acquire_single_instance(" + repr(name) + ");"
            "print('ok' if h is not None else 'none', flush=True);"
            "time.sleep(3)"
        )
        proc = subprocess.Popen(
            [sys.executable, "-c", code],
            stdout=subprocess.PIPE,
            text=True,
            encoding="utf-8",
        )
        try:
            line = proc.stdout.readline().strip()
            self.assertEqual(line, "ok")
            self.assertIsNone(single_instance.acquire_single_instance(name))
        finally:
            proc.terminate()
            try:
                proc.wait(timeout=3)
            except subprocess.TimeoutExpired:
                proc.kill()
                proc.wait()
            proc.stdout.close()

    def test_acquire_succeeds_after_holder_exits(self):
        name = "Local\\TestMoshidadan_" + uuid.uuid4().hex
        code = (
            "import single_instance;"
            "h = single_instance.acquire_single_instance(" + repr(name) + ");"
            "print('ok' if h is not None else 'none', flush=True)"
        )
        proc = subprocess.Popen(
            [sys.executable, "-c", code],
            stdout=subprocess.PIPE,
            text=True,
            encoding="utf-8",
        )
        out, _ = proc.communicate(timeout=5)
        self.assertEqual(out.strip(), "ok")
        handle = single_instance.acquire_single_instance(name)
        self.assertIsNotNone(handle)


if __name__ == "__main__":
    unittest.main()
