using System;
using System.Diagnostics;
using System.IO;
using System.Windows.Forms;
class Launcher {
    [STAThread] static void Main(string[] args) {
        string root = AppDomain.CurrentDomain.BaseDirectory;
        string runtime = Path.Combine(root, "runtime", "pythonw.exe");
        if (!File.Exists(runtime)) {
            MessageBox.Show("Распакуйте весь ZIP в одну папку. Рядом с EXE должны быть папки app и runtime.", "Хроники Хогвартса"); return;
        }
        try {
            var start = new ProcessStartInfo(runtime);
            start.Arguments = "\"" + Path.Combine(root, "app", "launch.py") + "\"" + (Array.IndexOf(args, "--personal") >= 0 ? " --personal" : "");
            start.WorkingDirectory = root;
            start.UseShellExecute = false;
            start.CreateNoWindow = true;
            start.WindowStyle = ProcessWindowStyle.Hidden;
            start.EnvironmentVariables["PYTHONNOUSERSITE"] = "1";
            start.EnvironmentVariables.Remove("PYTHONPATH");
            start.EnvironmentVariables.Remove("PYTHONHOME");
            Process.Start(start);
        } catch (Exception e) { MessageBox.Show(e.Message, "Хроники Хогвартса"); }
    }
}
