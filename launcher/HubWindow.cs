// Shared by the updater and the Edge app-window helper. No client windows are touched.
using System;
using System.Collections.Generic;
using System.Runtime.InteropServices;

namespace BotScape
{
    public static class HubWindow
    {
        public const string AppId = "BotScape.Hub";
        private static readonly Dictionary<int, IntPtr> Icons = new Dictionary<int, IntPtr>();

        [DllImport("shell32.dll", CharSet = CharSet.Unicode)]
        public static extern int SetCurrentProcessExplicitAppUserModelID(string appId);
        [DllImport("user32.dll", CharSet = CharSet.Unicode)]
        private static extern IntPtr LoadImage(IntPtr instance, string name, uint type, int cx, int cy, uint flags);
        [DllImport("user32.dll")]
        private static extern int GetSystemMetrics(int index);
        [DllImport("user32.dll", CharSet = CharSet.Unicode)]
        private static extern IntPtr SendMessageTimeout(IntPtr hwnd, uint msg, IntPtr wparam,
            IntPtr lparam, uint flags, uint timeout, out IntPtr result);
        [DllImport("user32.dll")]
        private static extern bool EnumWindows(EnumWindow callback, IntPtr data);
        private delegate bool EnumWindow(IntPtr hwnd, IntPtr data);
        [DllImport("user32.dll")]
        private static extern uint GetWindowThreadProcessId(IntPtr hwnd, out uint pid);
        [DllImport("user32.dll")]
        private static extern bool IsWindowVisible(IntPtr hwnd);
        [DllImport("user32.dll", CharSet = CharSet.Unicode)]
        private static extern int GetClassName(IntPtr hwnd, System.Text.StringBuilder name, int capacity);

        [StructLayout(LayoutKind.Sequential, Pack = 4)]
        private struct PropertyKey
        {
            public Guid Format;
            public uint Id;
            public PropertyKey(uint id) { Format = new Guid("9F4C2855-9F79-4B39-A8D0-E1D42DE1D5F3"); Id = id; }
        }
        // PROPVARIANT is 24 bytes on x64 (the counted-array union), 16 on x86.
        [StructLayout(LayoutKind.Explicit)]
        private struct PropVariant
        {
            [FieldOffset(0)] public ushort Type;
            [FieldOffset(8)] public IntPtr Text;
            [FieldOffset(8)] public CountedArray Array;
        }
        [StructLayout(LayoutKind.Sequential)]
        private struct CountedArray { public uint Count; public IntPtr Pointer; }

        [ComImport, Guid("886D8EEB-8CF2-4446-8D02-CDBA1DBDCF99"), InterfaceType(ComInterfaceType.InterfaceIsIUnknown)]
        private interface IPropertyStore
        {
            void GetCount(out uint count);
            void GetAt(uint index, out PropertyKey key);
            void GetValue(ref PropertyKey key, out PropVariant value);
            void SetValue(ref PropertyKey key, ref PropVariant value);
            void Commit();
        }
        [DllImport("shell32.dll", PreserveSig = false)]
        private static extern void SHGetPropertyStoreForWindow(IntPtr hwnd, ref Guid iid,
            [MarshalAs(UnmanagedType.Interface)] out IPropertyStore store);
        [DllImport("shell32.dll", CharSet = CharSet.Unicode, PreserveSig = false)]
        private static extern void SHGetPropertyStoreFromParsingName(string path, IntPtr context,
            uint flags, ref Guid iid, [MarshalAs(UnmanagedType.Interface)] out IPropertyStore store);

        public static void RefreshShortcuts(string folder, string launcherExe, bool subfolders = false)
        {
            // Preserve the existing no-new-shortcuts policy. An external installer
            // that targets BotScape.exe automatically gets its new embedded icon.
            // Repair older explicit shield icons only on links to this exact exe.
            if (!System.IO.Directory.Exists(folder)) return;
            var shell = Activator.CreateInstance(Type.GetTypeFromProgID("WScript.Shell"));
            try
            {
                foreach (var file in System.IO.Directory.GetFiles(folder, "*.lnk",
                    subfolders ? System.IO.SearchOption.AllDirectories : System.IO.SearchOption.TopDirectoryOnly))
                {
                    object link = null;
                    try
                    {
                        link = shell.GetType().InvokeMember("CreateShortcut", System.Reflection.BindingFlags.InvokeMethod,
                            null, shell, new object[] { file });
                        var target = (string)link.GetType().InvokeMember("TargetPath", System.Reflection.BindingFlags.GetProperty,
                            null, link, null);
                        if (!string.Equals(target, launcherExe, StringComparison.OrdinalIgnoreCase)) continue;
                        // The hub icon file itself, not the exe's: Windows' icon cache kept showing the old
                        // shield for the exe after an update (user-reported on the desktop shortcut).
                        var hubIcon = System.IO.Path.Combine(System.IO.Path.GetDirectoryName(launcherExe), "assets", "brand", "hub.ico");
                        link.GetType().InvokeMember("IconLocation", System.Reflection.BindingFlags.SetProperty,
                            null, link, new object[] { (System.IO.File.Exists(hubIcon) ? hubIcon : launcherExe) + ",0" });
                        link.GetType().InvokeMember("Save", System.Reflection.BindingFlags.InvokeMethod, null, link, null);
                        var iid = typeof(IPropertyStore).GUID;
                        IPropertyStore store;
                        SHGetPropertyStoreFromParsingName(file, IntPtr.Zero, 2, ref iid, out store); // GPS_READWRITE
                        try { Set(store, 5, AppId); store.Commit(); }
                        finally { Marshal.ReleaseComObject(store); }
                    }
                    catch (Exception ex) { System.Diagnostics.Debug.WriteLine(ex); }
                    finally { if (link != null) Marshal.FinalReleaseComObject(link); }
                }
            }
            finally { Marshal.FinalReleaseComObject(shell); }
        }

        private static void Set(IPropertyStore store, uint id, string text)
        {
            var key = new PropertyKey(id);
            var value = new PropVariant { Type = 31, Text = Marshal.StringToCoTaskMemUni(text) }; // VT_LPWSTR
            try { store.SetValue(ref key, ref value); }
            finally { Marshal.FreeCoTaskMem(value.Text); }
        }

        public static void Apply(IntPtr hwnd, string iconFile, string launcherExe)
        {
            var iid = typeof(IPropertyStore).GUID;
            IPropertyStore store;
            SHGetPropertyStoreForWindow(hwnd, ref iid, out store);
            try
            {
                // Set relaunch properties before the explicit ID, as required by the shell:
                // https://learn.microsoft.com/windows/win32/shell/appids
                Set(store, 2, "\"" + launcherExe + "\"");
                Set(store, 3, iconFile + ",0");
                Set(store, 4, "Bot Scape Hub");
                Set(store, 5, AppId);
                store.Commit();
            }
            finally { Marshal.ReleaseComObject(store); }
            for (int kind = 0; kind <= 1; kind++)
            {
                int size = GetSystemMetrics(kind == 0 ? 49 : 11); // small / large icon width
                IntPtr icon;
                if (!Icons.TryGetValue(size, out icon))
                {
                    icon = LoadImage(IntPtr.Zero, iconFile, 1, size, size, 0x10); // IMAGE_ICON, LR_LOADFROMFILE
                    if (icon == IntPtr.Zero) throw new System.ComponentModel.Win32Exception();
                    Icons.Add(size, icon);
                }
                IntPtr ignored;
                SendMessageTimeout(hwnd, 0x80, (IntPtr)kind, icon, 2, 1000, out ignored); // WM_SETICON
            }
        }

        public static int ApplyToProcess(int processId, string iconFile, string launcherExe)
        {
            int count = 0;
            EnumWindows(delegate(IntPtr hwnd, IntPtr data)
            {
                uint pid;
                GetWindowThreadProcessId(hwnd, out pid);
                var name = new System.Text.StringBuilder(128);
                GetClassName(hwnd, name, name.Capacity);
                if (pid == processId && IsWindowVisible(hwnd) && name.ToString() == "Chrome_WidgetWin_1")
                {
                    // The window can close between enumeration and shell assignment.
                    try { Apply(hwnd, iconFile, launcherExe); count++; }
                    catch (Exception ex) { System.Diagnostics.Debug.WriteLine(ex); }
                }
                return true;
            }, IntPtr.Zero);
            return count;
        }
    }
}
