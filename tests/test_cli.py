import io
import unittest
from contextlib import redirect_stdout
from unittest.mock import patch

from sjef import cli
from sjef.picnic import login_setup


class CliTests(unittest.TestCase):
    def test_picnic_login_subcommand_forwards_options(self):
        for options in (
            [],
            ["--start", "--channel", "EMAIL"],
            ["--verify", "123456"],
        ):
            with self.subTest(options=options):
                with patch.object(login_setup, "main") as login:
                    cli.main(["picnic-login", *options])
                login.assert_called_once_with(options)

    def test_picnic_login_help_does_not_load_credentials(self):
        with (
            patch.object(login_setup.Secrets, "load") as load,
            redirect_stdout(io.StringIO()) as output,
            self.assertRaises(SystemExit) as error,
        ):
            cli.main(["picnic-login", "--help"])
        self.assertEqual(error.exception.code, 0)
        self.assertIn("--verify", output.getvalue())
        load.assert_not_called()

    def test_no_command_shows_help_without_running_selftests(self):
        output = io.StringIO()
        with (
            patch.object(cli, "run_selftest", return_value=0) as selftest,
            redirect_stdout(output),
        ):
            self.assertEqual(cli.main([]), 0)
        selftest.assert_not_called()
        self.assertIn("dashboard", output.getvalue())
        self.assertIn("selftest", output.getvalue())

    def test_dashboard_subcommand_forwards_arguments_and_exit_code(self):
        for options in ([], ["--server.port", "8502"], ["--help"]):
            with self.subTest(options=options):
                with patch.object(cli.subprocess, "call", return_value=3) as launch:
                    self.assertEqual(cli.main(["dashboard", *options]), 3)
                self.assertEqual(launch.call_args.args[0][5:], options)

    def test_plan_passes_mode(self):
        with patch.object(cli, "run_plan") as plan:
            cli.main(["plan", "bulk"])
        plan.assert_called_once_with("bulk")

    def test_invalid_arguments_do_not_start_bot(self):
        with (
            patch.object(cli, "run_bot") as bot,
            self.assertRaises(SystemExit) as error,
        ):
            cli.main(["bot", "unexpected"])
        self.assertEqual(error.exception.code, 2)
        bot.assert_not_called()

    def test_selftest_failure_is_returned(self):
        with patch.object(cli, "run_selftest", return_value=2):
            self.assertEqual(cli.main(["selftest"]), 2)

    def test_dashboard_forwards_options_and_exit_code(self):
        with (
            patch.object(cli.subprocess, "call", return_value=3) as launch,
        ):
            self.assertEqual(cli.main(["dashboard", "--server.port", "8502"]), 3)
        args = launch.call_args.args[0]
        self.assertEqual(args[:4], [cli.sys.executable, "-m", "streamlit", "run"])
        self.assertTrue(args[4].endswith("sjef/interfaces/dashboard.py"))
        self.assertEqual(args[5:], ["--server.port", "8502"])
