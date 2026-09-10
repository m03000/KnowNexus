using System;
using System.Diagnostics;
using System.IO;
using System.Reflection;
using System.Windows.Forms;

[assembly: AssemblyTitle("KnowNexus Launcher")]
[assembly: AssemblyProduct("KnowNexus")]
[assembly: AssemblyDescription("KnowNexus portable launcher")]
[assembly: AssemblyCompany("KnowNexus Contributors")]
[assembly: AssemblyVersion("0.1.0.0")]
[assembly: AssemblyFileVersion("0.1.0.0")]

internal static class KnowNexusLauncher
{
    [STAThread]
    private static void Main()
    {
        string directory = AppDomain.CurrentDomain.BaseDirectory;
        string executable = Path.Combine(directory, "KnowNexus.exe");
        if (!File.Exists(executable))
        {
            MessageBox.Show("没有在当前目录找到 KnowNexus.exe。请完整解压便携包后再启动。", "KnowNexus", MessageBoxButtons.OK, MessageBoxIcon.Error);
            return;
        }
        Process.Start(new ProcessStartInfo(executable) { WorkingDirectory = directory, UseShellExecute = true });
    }
}
