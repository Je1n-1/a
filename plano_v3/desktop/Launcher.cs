using System;
using System.Collections.Generic;
using System.Diagnostics;
using System.Drawing;
using System.IO;
using System.Net;
using System.Net.Sockets;
using System.Security.Cryptography;
using System.Text;
using System.Threading;
using System.Web.Script.Serialization;
using System.Windows.Forms;

// Small Windows launcher. Python, application files and the existing database
// stay in their original locations; this program never initializes a database.
internal static class Launcher
{
    internal static string Url, LogPath, Database;
    static readonly object LogLock = new object();
    static readonly JavaScriptSerializer Json = new JavaScriptSerializer();
    static bool Quiet { get { return Environment.GetEnvironmentVariable("PLANO_LAUNCHER_NO_BROWSER") == "1"; } }

    [STAThread]
    static int Main(string[] args)
    {
        Application.EnableVisualStyles();
        string root = AppDomain.CurrentDomain.BaseDirectory;
        string identity;
        using (var hash = SHA256.Create())
            identity = BitConverter.ToString(hash.ComputeHash(Encoding.UTF8.GetBytes(root.ToLowerInvariant()))).Replace("-", "");
        string stopName = "Local\\PlanoStop-" + identity;
        if (Array.IndexOf(args, "--stop") >= 0)
        {
            try { using (var stop = EventWaitHandle.OpenExisting(stopName)) stop.Set(); return 0; }
            catch (WaitHandleCannotBeOpenedException) { return 0; }
        }
        Process server = null;
        try
        {
            string logs = Path.Combine(Environment.GetFolderPath(Environment.SpecialFolder.LocalApplicationData), "PlanoV3", "logs");
            Directory.CreateDirectory(logs);
            LogPath = Path.Combine(logs, "launcher-" + DateTime.Now.ToString("yyyyMMdd-HHmmss-fff") + "-" + Process.GetCurrentProcess().Id + ".log");
            var config = Json.Deserialize<Dictionary<string, object>>(File.ReadAllText(Path.Combine(root, "config.local.json"), Encoding.UTF8));
            Database = Convert.ToString(config["database_path"]);
            int port = Convert.ToInt32(config["port"]);
            if (port < 1024 || port > 65535 || !Path.IsPathRooted(Database) || !File.Exists(Database))
                throw new Exception("O banco configurado não foi encontrado ou a porta é inválida. Nenhum banco novo foi criado.");
            Database = Path.GetFullPath(Database);
            Url = "http://127.0.0.1:" + port + "/";
            bool created;
            using (var singleton = new Mutex(true, "Local\\PlanoLauncher-" + identity, out created))
            {
                if (!created)
                {
                    for (int i = 0; i < 80; i++)
                    {
                        if (Healthy()) { OpenBrowser(); return 0; }
                        Thread.Sleep(250);
                    }
                    throw new Exception("O Plano já está iniciando. Aguarde e tente abrir novamente.");
                }
                using (var stop = new EventWaitHandle(false, EventResetMode.ManualReset, stopName))
                {
                    if (Healthy()) { OpenBrowser(); return 0; }
                    if (PortOccupied(port)) throw new Exception("A porta " + port + " está ocupada por outro serviço. Ele não foi encerrado.");
                    string python = config.ContainsKey("python_path") ? Convert.ToString(config["python_path"]) : Path.Combine(root, ".venv", "Scripts", "python.exe");
                    string app = Path.Combine(root, "app.py");
                    if (!File.Exists(python) || !File.Exists(app))
                        throw new Exception("A instalação do Plano não foi encontrada. Mantenha Plano.exe na pasta do site, junto de app.py e .venv.");
                    var info = new ProcessStartInfo(python, Quote(app) + " --database " + Quote(Database) + " --port " + port);
                    info.WorkingDirectory = root;
                    info.UseShellExecute = false;
                    info.CreateNoWindow = true;
                    info.WindowStyle = ProcessWindowStyle.Hidden;
                    info.RedirectStandardOutput = true;
                    info.RedirectStandardError = true;
                    info.EnvironmentVariables["PYTHONUTF8"] = "1";
                    info.EnvironmentVariables["PYTHONUNBUFFERED"] = "1";
                    server = new Process { StartInfo = info };
                    server.OutputDataReceived += delegate(object sender, DataReceivedEventArgs e) { WriteLog(e.Data); };
                    server.ErrorDataReceived += delegate(object sender, DataReceivedEventArgs e) { WriteLog(e.Data); };
                    WriteLog("Iniciando " + Url + " Banco: " + Database);
                    server.Start();server.BeginOutputReadLine();server.BeginErrorReadLine();
                    bool ready = false;
                    for (int i = 0; i < 80; i++)
                    {
                        if (stop.WaitOne(0)) return 0;
                        if (server.HasExited) throw new Exception("O servidor não conseguiu iniciar. Consulte o registro para ver o motivo.");
                        if (Healthy()) { ready = true; break; }
                        Thread.Sleep(250);
                    }
                    if (!ready) throw new Exception("O servidor não respondeu a tempo. Consulte o registro de inicialização.");
                    OpenBrowser();
                    using (var context = new TrayContext(server, stop)) Application.Run(context);
                }
            }
            return 0;
        }
        catch (Exception error)
        {
            WriteLog(error.ToString());
            if (!Quiet) MessageBox.Show(error.Message + "\n\nRegistro: " + (LogPath ?? "indisponível"), "Plano — não foi possível abrir", MessageBoxButtons.OK, MessageBoxIcon.Error);
            return 1;
        }
        finally { StopOwned(server); }
    }

    static string Quote(string value)
    {
        // Windows paths cannot contain double quotes. Every path here is a file,
        // so no trailing backslash needs the extra command-line escaping rule.
        if (value.IndexOf('"') >= 0) throw new Exception("Caminho de arquivo inválido.");
        return "\"" + value + "\"";
    }

    static bool Healthy()
    {
        try
        {
            var request = (HttpWebRequest)WebRequest.Create(Url + "api/diagnostics");
            request.Proxy = null;request.Timeout = 1500;request.ReadWriteTimeout = 1500;
            using (var response = request.GetResponse())
            using (var reader = new StreamReader(response.GetResponseStream()))
            {
                var result = Json.Deserialize<Dictionary<string, object>>(reader.ReadToEnd());
                return Convert.ToString(result["integrity"]) == "ok" && String.Equals(Path.GetFullPath(Convert.ToString(result["path"])), Database, StringComparison.OrdinalIgnoreCase);
            }
        }
        catch { return false; }
    }

    static bool PortOccupied(int port)
    {
        using (var client = new TcpClient())
        {
            try { client.Connect("127.0.0.1", port);return true; }
            catch (SocketException) { return false; }
        }
    }

    internal static void OpenBrowser()
    {
        if (!Quiet) Process.Start(new ProcessStartInfo(Url) { UseShellExecute = true });
    }

    internal static void WriteLog(string line)
    {
        if (line == null || LogPath == null) return;
        try { lock (LogLock) File.AppendAllText(LogPath, DateTime.Now.ToString("s") + " " + line + Environment.NewLine, Encoding.UTF8); }
        catch { /* A full log disk must not interrupt a study session. */ }
    }

    static void StopOwned(Process server)
    {
        if (server == null) return;
        try
        {
            if (!server.HasExited)
            {
                // Only this launcher's process tree: .venv may forward to a child.
                var info = new ProcessStartInfo(Path.Combine(Environment.GetFolderPath(Environment.SpecialFolder.System), "taskkill.exe"), "/PID " + server.Id + " /T /F");
                info.UseShellExecute = false;info.CreateNoWindow = true;info.WindowStyle = ProcessWindowStyle.Hidden;
                using (var kill = Process.Start(info)) kill.WaitForExit(10000);
                server.WaitForExit(5000);
            }
        }
        catch (Exception e) { WriteLog("Ao encerrar: " + e.Message); }
        finally { server.Dispose(); }
    }
}

internal sealed class TrayContext : ApplicationContext
{
    readonly NotifyIcon icon;
    readonly System.Windows.Forms.Timer watch;
    readonly Process server;
    readonly EventWaitHandle stop;
    bool disposed;

    internal TrayContext(Process process, EventWaitHandle signal)
    {
        server=process;stop=signal;
        var menu = new ContextMenuStrip();
        menu.Items.Add("Abrir Plano", null, delegate { Launcher.OpenBrowser(); });
        menu.Items.Add("Abrir registro de inicialização", null, delegate { Process.Start(new ProcessStartInfo(Launcher.LogPath) { UseShellExecute=true }); });
        menu.Items.Add(new ToolStripSeparator());
        menu.Items.Add("Encerrar servidor do Plano", null, delegate { ExitThread(); });
        icon = new NotifyIcon { Icon=Icon.ExtractAssociatedIcon(Application.ExecutablePath), Text="Plano — servidor local em execução", ContextMenuStrip=menu, Visible=true };
        icon.DoubleClick += delegate { Launcher.OpenBrowser(); };
        watch = new System.Windows.Forms.Timer { Interval=500 };
        watch.Tick += delegate {
            if (stop.WaitOne(0)) ExitThread();
            else if (server.HasExited)
            {
                Launcher.WriteLog("O servidor foi encerrado.");
                ExitThread();
            }
        };
        watch.Start();
    }
    protected override void Dispose(bool disposing)
    {
        if (disposing && !disposed)
        {
            disposed=true;
            watch.Stop();watch.Dispose();icon.Visible=false;
            if (icon.ContextMenuStrip != null) icon.ContextMenuStrip.Dispose();
            if (icon.Icon != null) icon.Icon.Dispose();
            icon.Dispose();
        }
        base.Dispose(disposing);
    }
}
