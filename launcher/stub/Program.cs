using System;
using System.Collections.Generic;
using System.Diagnostics;
using System.Drawing;
using System.IO;
using System.Linq;
using System.Net;
using System.Net.Http;
using System.Threading;
using System.Threading.Tasks;
using System.Web.Script.Serialization;
using System.Windows.Forms;

namespace BotScape
{
    /// <summary>
    /// Bot Scape's launcher: shows a small window while it checks zazuosu.com for a new version of
    /// the game (downloads/botscape/manifest.json, the same list the Zazuosu launcher installs
    /// from), downloads what changed (no desktop shortcut: user-requested), then opens the
    /// Bot Scape hub (LAUNCHER.pyw) and closes. Arguments (e.g. the Zazuosu launcher's
    /// --authtoken=...) are passed on to the hub.
    /// </summary>
    internal static class Program
    {
        [STAThread]
        private static void Main(string[] args)
        {
            ServicePointManager.SecurityProtocol = SecurityProtocolType.Tls12;
            HubWindow.SetCurrentProcessExplicitAppUserModelID(HubWindow.AppId);
            try
            {
                HubWindow.RefreshShortcuts(Environment.GetFolderPath(Environment.SpecialFolder.DesktopDirectory), Application.ExecutablePath);
                HubWindow.RefreshShortcuts(Environment.GetFolderPath(Environment.SpecialFolder.Programs), Application.ExecutablePath, true);
            }
            catch (Exception ex) { Debug.WriteLine(ex); }
            Application.EnableVisualStyles();
            Application.SetCompatibleTextRenderingDefault(false);
            Application.Run(new UpdateWindow(args));
        }

        internal static string Root => AppDomain.CurrentDomain.BaseDirectory;

        /// <summary>
        /// The development checkout (it has the server's source next to it): never update it from the
        /// published package, which would overwrite newer work with older copies.
        /// </summary>
        internal static bool IsDevFolder => Directory.Exists(Path.Combine(Root, "rsmod"));
    }

    internal sealed class UpdateWindow : Form
    {
        private readonly string[] _args;
        private readonly Label _status = new Label();
        private readonly ProgressBar _bar = new ProgressBar();
        private readonly Label _detail = new Label();   // user-requested: MB done, MB/s, and when it's ready

        public UpdateWindow(string[] args)
        {
            _args = args;
            Text = "BotScape Hub";
            FormBorderStyle = FormBorderStyle.FixedSingle;
            MaximizeBox = false;
            StartPosition = FormStartPosition.CenterScreen;
            ClientSize = new Size(420, 170);
            BackColor = Color.FromArgb(15, 17, 21);
            ForeColor = Color.FromArgb(230, 230, 230);
            try { Icon = Icon.ExtractAssociatedIcon(typeof(Program).Assembly.Location); } catch { }

            var logo = new PictureBox { Size = new Size(64, 64), Location = new Point(20, 20), SizeMode = PictureBoxSizeMode.Zoom };
            // Read into memory, never Image.FromFile: that keeps the file locked while the window is open, and the
            // update couldn't replace it (user-reported 2026-11-13: an endless "Couldn't check for updates" loop).
            var logoFile = Path.Combine(Program.Root, "assets", "brand", "updater-logo.png");
            if (!File.Exists(logoFile)) logoFile = Path.Combine(Program.Root, "assets", "brand", "hub-128.png");
            try { if (File.Exists(logoFile)) logo.Image = new Bitmap(new MemoryStream(File.ReadAllBytes(logoFile))); } catch { }
            var title = new Label
            {
                Text = "BOT SCAPE", Location = new Point(96, 30), AutoSize = true,
                Font = new Font("Segoe UI", 18, FontStyle.Bold), ForeColor = Color.FromArgb(232, 179, 57),
            };
            _status.Location = new Point(98, 66);
            _status.Size = new Size(300, 20);
            _status.Text = "Checking for updates…";
            _bar.Location = new Point(20, 110);
            _bar.Size = new Size(380, 18);
            _detail.Location = new Point(20, 134);
            _detail.Size = new Size(380, 20);
            _detail.ForeColor = Color.FromArgb(160, 166, 176);
            Controls.AddRange(new Control[] { logo, title, _status, _bar, _detail });
            Shown += async (s, e) => await RunAsync();
        }

        private async Task RunAsync()
        {
            try
            {
                if (Program.IsDevFolder)
                {
                    SetStatus("Development folder: not updating.");
                    await Task.Delay(500);
                }
                else
                {
                    await UpdateAsync();
                }
            }
            catch (Exception ex)
            {
                // Offline or the server is down: play what's installed. What went wrong goes in a log file
                // (it used to go nowhere).
                Debug.WriteLine(ex);
                LogError("update check", ex);
                SetStatus("Couldn't check for updates; starting anyway.");
                await Task.Delay(800);
            }
            // --update-only: just update (testing, or an installer step), no hub.
            if (_args.Contains("--update-only"))
            {
                Close();
                return;
            }
            StartHub();
            Close();
        }

        private void SetStatus(string text) => _status.Text = text;

        /// <summary>launcher/update-error.log: what an update couldn't do, for finding out why.</summary>
        private static void LogError(string what, Exception ex)
        {
            try
            {
                var log = Path.Combine(Program.Root, "launcher", "update-error.log");
                Directory.CreateDirectory(Path.GetDirectoryName(log));
                File.AppendAllText(log, $"{DateTime.Now:yyyy-MM-dd HH:mm:ss}  {what}: {ex.GetType().Name}: {ex.Message}{Environment.NewLine}");
            }
            catch { }
        }

        private static string Local(string path) => Path.Combine(Program.Root, path.Replace('/', Path.DirectorySeparatorChar));

        private async Task UpdateAsync()
        {
            var json = new JavaScriptSerializer { MaxJsonLength = int.MaxValue };
            using (var http = new HttpClient { Timeout = TimeSpan.FromMinutes(10) })
            {
                var text = await http.GetStringAsync(Program_ManifestUrl() + "?t=" + DateTime.UtcNow.Ticks);
                var manifest = json.Deserialize<Manifest>(text);
                var versionFile = Path.Combine(Program.Root, "version.txt");
                var installedFile = Path.Combine(Program.Root, "installed.json");
                var installed = File.Exists(installedFile)
                    ? json.Deserialize<Dictionary<string, string>>(File.ReadAllText(installedFile)) ?? new Dictionary<string, string>()
                    : new Dictionary<string, string>();

                var todo = manifest.files.Where(f =>
                {
                    var local = Local(f.path);
                    return !File.Exists(local) || new FileInfo(local).Length != f.size ||
                           !installed.TryGetValue(f.path, out var id) || id != f.id;
                }).ToList();
                if (todo.Count == 0)
                {
                    SetStatus("BotScape Hub " + manifest.version + " is up to date.");
                    _bar.Value = 100;
                    await Task.Delay(300);
                    return;
                }

                long total = Math.Max(1, todo.Sum(f => f.size)), done = 0;
                var failed = 0;
                var clock = Stopwatch.StartNew();
                long shownAt = -1000;
                foreach (var f in todo)
                {
                    SetStatus($"Updating to {manifest.version}: {Path.GetFileName(f.path)}");
                    var url = f.url ?? manifest.@base.TrimEnd('/') + "/" +
                              string.Join("/", f.path.Split('/').Select(Uri.EscapeDataString)) + "?v=" + Uri.EscapeDataString(f.id);
                    var local = Local(f.path);
                    Directory.CreateDirectory(Path.GetDirectoryName(local));
                    var temp = local + ".download";
                    using (var response = await http.GetAsync(url, HttpCompletionOption.ResponseHeadersRead))
                    {
                        response.EnsureSuccessStatusCode();
                        using (var input = await response.Content.ReadAsStreamAsync())
                        using (var output = File.Create(temp))
                        {
                            var buffer = new byte[81920];
                            int read;
                            while ((read = await input.ReadAsync(buffer, 0, buffer.Length)) > 0)
                            {
                                await output.WriteAsync(buffer, 0, read);
                                done += read;
                                _bar.Value = (int)Math.Min(100, done * 100 / total);
                                if (clock.ElapsedMilliseconds - shownAt >= 250)
                                {
                                    shownAt = clock.ElapsedMilliseconds;
                                    var speed = done / Math.Max(0.001, clock.Elapsed.TotalSeconds) / 1048576.0;
                                    _detail.Text = $"{done / 1048576.0:0.0} / {total / 1048576.0:0.0} MB  ·  {speed:0.0} MB/s";
                                }
                            }
                        }
                    }
                    try
                    {
                        Replace(temp, local);
                    }
                    catch (Exception ex) when (ex is IOException || ex is UnauthorizedAccessException)
                    {
                        // A file in use can't be replaced: leave it, carry on with the rest, and try it again next
                        // time (one locked file used to stop the whole update, every time).
                        LogError("replace " + f.path, ex);
                        failed++;
                        try { File.Delete(temp); } catch { }
                        continue;
                    }
                    installed[f.path] = f.id;
                    File.WriteAllText(installedFile, json.Serialize(installed));
                }
                // Done (a file still in use waits for the next update; the hub's own files are never in use here).
                File.WriteAllText(versionFile, manifest.version);
                SetStatus("Updated to BotScape Hub " + manifest.version + ".");
                _bar.Value = 100;
                _detail.ForeColor = Color.FromArgb(63, 185, 107);
                _detail.Text = $"Ready! {total / 1048576.0:0.0} MB in {clock.Elapsed.TotalSeconds:0} s. Starting BotScape Hub…";
                await Task.Delay(1200);
            }
        }

        private static string Program_ManifestUrl()
        {
            // A botscape-launcher.json next to the exe can point somewhere else (testing).
            var config = Path.Combine(Program.Root, "botscape-launcher.json");
            if (File.Exists(config))
            {
                var settings = new JavaScriptSerializer().Deserialize<Dictionary<string, object>>(File.ReadAllText(config));
                if (settings != null && settings.TryGetValue("manifestUrl", out var url) && url is string s && s.Length > 0) return s;
            }
            return "https://zazuosu.com/downloads/botscape/manifest.json";
        }

        /// <summary>Puts a downloaded file in place. A running exe (this one) can't be overwritten,
        /// but it can be renamed out of the way first.</summary>
        private static void Replace(string temp, string local)
        {
            if (File.Exists(local))
            {
                try { File.Delete(local); }
                catch (IOException)
                {
                    var old = local + ".old";
                    if (File.Exists(old)) File.Delete(old);
                    File.Move(local, old);
                }
                catch (UnauthorizedAccessException)
                {
                    var old = local + ".old";
                    if (File.Exists(old)) File.Delete(old);
                    File.Move(local, old);
                }
            }
            File.Move(temp, local);
        }

        /// <summary>Opens the hub with the bundled Python (or the system's), passing our arguments on.</summary>
        private void StartHub()
        {
            var bundled = Path.Combine(Program.Root, "runtime", "python", "pythonw.exe");
            var python = File.Exists(bundled) ? bundled : "pythonw";
            var args = "\"" + Path.Combine(Program.Root, "LAUNCHER.pyw") + "\" " +
                       string.Join(" ", _args.Select(a => a.Contains(" ") ? "\"" + a + "\"" : a));
            try
            {
                Process.Start(new ProcessStartInfo(python, args) { WorkingDirectory = Program.Root, UseShellExecute = false, CreateNoWindow = true });
            }
            catch (Exception ex)
            {
                MessageBox.Show("Couldn't start BotScape Hub: " + ex.Message, "BotScape Hub", MessageBoxButtons.OK, MessageBoxIcon.Error);
            }
        }
    }

    // downloads/botscape/manifest.json (same shape as the Zazuosu launcher's file manifests).
    internal sealed class Manifest
    {
        public string version { get; set; } = "0.0.0";
        public string notes { get; set; } = "";
        public string @base { get; set; } = "";
        public List<ManifestFile> files { get; set; } = new List<ManifestFile>();
    }

    internal sealed class ManifestFile
    {
        public string path { get; set; } = "";
        public long size { get; set; }
        public string id { get; set; } = "";
        public string url { get; set; }
    }
}
