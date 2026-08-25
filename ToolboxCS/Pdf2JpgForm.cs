// Pdf2JpgForm.cs — PDF 转 JPG 工具页（Win95 风格）
// 功能：拖拽/按钮添加 PDF、输出目录、1x/2x/3x 分辨率、后台转换、
//       进度条、日志列表、右键菜单（打开/打开文件夹/另存为/删除）、悬停状态提示
using System.Diagnostics;
using System.Runtime.InteropServices;
using Docnet.Core;
using Docnet.Core.Models;

namespace ToolboxCS;

public class Pdf2JpgForm : Form
{
    private ListBox _listFiles;
    private ListBox _listLog;
    private TextBox _editOutdir;
    private RadioButton _radio1x, _radio2x, _radio3x;
    private Button _btnConvert;
    private ProgressBar _progress;
    private Label _lblStatus;
    private string _statusBackup = "";

    // 日志项 → 输出文件路径（右键操作用）
    private readonly Dictionary<int, List<string>> _logPaths = new();
    private int _logSeq;

    public Pdf2JpgForm()
    {
        Text = "PDF 转 JPG";
        var ic = MainForm.AppIcon;
        if (ic != null) Icon = ic;
        ClientSize = new Size(620, 480);
        MinimumSize = new Size(560, 420 + 39);
        StartPosition = FormStartPosition.CenterParent;
        Font = new Font("Microsoft YaHei UI", 9F);
        BackColor = Win95.Face;
        AllowDrop = true;

        BuildUi();
        BindHints();
        Win95.Apply(this);
    }

    private void BuildUi()
    {
        // ── 顶栏：返回 + 标题 ───────────────────────
        var top = new FlowLayoutPanel
        {
            Dock = DockStyle.Top,
            Height = 40,
            FlowDirection = FlowDirection.LeftToRight,
            BackColor = Win95.Face,
            Padding = new Padding(4, 4, 0, 0),
            WrapContents = false,
        };
        var btnBack = new Button { Text = "← 返回", AutoSize = true };
        Win95.StyleButton(btnBack);
        btnBack.Click += (s, e) => Close();
        top.Controls.Add(btnBack);

        top.Controls.Add(new PictureBox
        {
            Image = MainForm.LoadPng(),
            SizeMode = PictureBoxSizeMode.Zoom,
            Size = new Size(24, 24),
            Margin = new Padding(10, 4, 0, 0),
        });
        top.Controls.Add(new Label
        {
            Text = "PDF 转 JPG",
            Font = new Font("Microsoft YaHei UI", 11F, FontStyle.Bold),
            AutoSize = true,
            Margin = new Padding(6, 6, 0, 0),
        });
        Controls.Add(top);

        // ── 主体 ───────────────────────────────────
        var body = new TableLayoutPanel
        {
            Dock = DockStyle.Fill,
            ColumnCount = 1,
            RowCount = 8,
            BackColor = Win95.Face,
            Padding = new Padding(8, 4, 8, 4),
        };
        body.RowStyles.Add(new RowStyle(SizeType.AutoSize));           // 按钮行
        body.RowStyles.Add(new RowStyle(SizeType.Percent, 55));        // 文件列表
        body.RowStyles.Add(new RowStyle(SizeType.AutoSize));           // 输出目录行
        body.RowStyles.Add(new RowStyle(SizeType.AutoSize));           // 分辨率行
        body.RowStyles.Add(new RowStyle(SizeType.AutoSize));           // 转换按钮
        body.RowStyles.Add(new RowStyle(SizeType.AutoSize));           // 进度条
        body.RowStyles.Add(new RowStyle(SizeType.Percent, 45));        // 日志
        body.RowStyles.Add(new RowStyle(SizeType.AutoSize));           // 状态栏
        Controls.Add(body);
        body.BringToFront();

        // 行1：文件操作按钮
        var btnRow = new FlowLayoutPanel { Dock = DockStyle.Fill, AutoSize = true, WrapContents = false, BackColor = Win95.Face };
        var btnAdd = new Button { Text = "添加 PDF 文件", AutoSize = true };
        var btnAddDir = new Button { Text = "添加文件夹", AutoSize = true };
        var btnClear = new Button { Text = "清空列表", AutoSize = true };
        Win95.StyleButton(btnAdd); Win95.StyleButton(btnAddDir); Win95.StyleButton(btnClear);
        btnAdd.Click += (s, e) => AddFilesDialog();
        btnAddDir.Click += (s, e) => AddDirDialog();
        btnClear.Click += (s, e) => { _listFiles.Items.Clear(); UpdateStatus(); };
        btnRow.Controls.AddRange(new Control[] { btnAdd, btnAddDir, new Panel { Width = 200 }, btnClear });
        body.Controls.Add(btnRow, 0, 0);

        // 行2：文件列表
        _listFiles = new ListBox { Dock = DockStyle.Fill, IntegralHeight = false, AllowDrop = true, ItemHeight = 18 };
        _listFiles.DragEnter += (s, e) => { if (e.Data.GetDataPresent(DataFormats.FileDrop)) e.Effect = DragDropEffects.Copy; };
        _listFiles.DragDrop += (s, e) => AddPaths((string[])e.Data.GetData(DataFormats.FileDrop));
        _listFiles.MouseClick += (s, e) => { if (e.Button == MouseButtons.Right) PopupMenu(_listFiles, e.Location); };
        body.Controls.Add(_listFiles, 0, 1);

        // 行3：输出目录（TableLayoutPanel 精确对齐）
        const int rowH = 28; // 统一行高
        var outRow = new TableLayoutPanel { Dock = DockStyle.Fill, Height = rowH, BackColor = Win95.Face, Margin = new Padding(0, 8, 0, 0) };
        outRow.ColumnCount = 3;
        outRow.RowCount = 1;
        outRow.ColumnStyles.Add(new ColumnStyle(SizeType.AutoSize));     // 标签
        outRow.ColumnStyles.Add(new ColumnStyle(SizeType.Percent, 100)); // 输入框
        outRow.ColumnStyles.Add(new ColumnStyle(SizeType.AutoSize));     // 按钮

        var lblOut = new Label { Text = "输出目录:", AutoSize = true, TextAlign = ContentAlignment.MiddleLeft, Height = rowH, Padding = new Padding(0, 4, 0, 0) };
        _editOutdir = new TextBox { Dock = DockStyle.Fill, Height = rowH, Margin = new Padding(4, 0, 4, 0) };
        var btnBrowse = new Button { Text = "浏 览", Width = 60, Height = rowH, Margin = new Padding(0, 0, 0, 0) };
        Win95.StyleButton(btnBrowse);
        btnBrowse.Click += (s, e) =>
        {
            using var d = new FolderBrowserDialog { Description = "选择输出目录" };
            if (d.ShowDialog(this) == DialogResult.OK) _editOutdir.Text = d.SelectedPath;
        };
        outRow.Controls.AddRange(new Control[] { lblOut, _editOutdir, btnBrowse });
        body.Controls.Add(outRow, 0, 2);

        // 行4：分辨率（TableLayoutPanel 精确对齐）
        var zoomRow = new TableLayoutPanel { Dock = DockStyle.Fill, Height = rowH, BackColor = Win95.Face, Margin = new Padding(0, 6, 0, 0) };
        zoomRow.ColumnCount = 5;
        zoomRow.RowCount = 1;
        zoomRow.ColumnStyles.Add(new ColumnStyle(SizeType.AutoSize));    // 标签
        zoomRow.ColumnStyles.Add(new ColumnStyle(SizeType.AutoSize));    // 1x
        zoomRow.ColumnStyles.Add(new ColumnStyle(SizeType.AutoSize));    // 2x
        zoomRow.ColumnStyles.Add(new ColumnStyle(SizeType.AutoSize));    // 3x
        zoomRow.ColumnStyles.Add(new ColumnStyle(SizeType.Percent, 100));// 弹性填充+按钮

        var lblZoom = new Label { Text = "分辨率:", AutoSize = true, TextAlign = ContentAlignment.MiddleLeft, Height = rowH, Padding = new Padding(0, 4, 0, 0) };
        _radio1x = new RadioButton { Text = "1x 快速", AutoSize = true, Height = rowH, Padding = new Padding(0, 4, 0, 0) };
        _radio2x = new RadioButton { Text = "2x 清晰", AutoSize = true, Checked = true, Height = rowH, Padding = new Padding(0, 4, 0, 0) };
        _radio3x = new RadioButton { Text = "3x 高清", AutoSize = true, Height = rowH, Padding = new Padding(0, 4, 0, 0) };

        // 右侧弹性面板放按钮
        var zoomRight = new FlowLayoutPanel { Dock = DockStyle.Fill, FlowDirection = FlowDirection.RightToLeft, BackColor = Win95.Face, WrapContents = false, Padding = new Padding(0, 0, 0, 0) };
        var btnOpenOut = new Button { Text = "打开输出目录", AutoSize = true, Height = rowH - 2 };
        Win95.StyleButton(btnOpenOut);
        btnOpenOut.Click += (s, e) => OpenOutdir();
        zoomRight.Controls.Add(btnOpenOut);

        zoomRow.Controls.AddRange(new Control[] { lblZoom, _radio1x, _radio2x, _radio3x, zoomRight });
        body.Controls.Add(zoomRow, 0, 3);

        // 行5：开始转换
        _btnConvert = new Button { Text = "开始转换", Dock = DockStyle.Fill, Height = 30, BackColor = Win95.Face };
        _btnConvert.ForeColor = Win95.Navy;
        _btnConvert.Font = new Font("Microsoft YaHei UI", 9.5F, FontStyle.Bold);
        Win95.StyleButton(_btnConvert);
        _btnConvert.Click += async (s, e) => await StartConvertAsync();
        body.Controls.Add(_btnConvert, 0, 4);

        // 行6：进度条
        _progress = new ProgressBar { Dock = DockStyle.Fill, Height = 16, Visible = false };
        body.Controls.Add(_progress, 0, 5);

        // 行7：日志
        _listLog = new ListBox { Dock = DockStyle.Fill, IntegralHeight = false, ItemHeight = 18 };
        _listLog.MouseClick += (s, e) => { if (e.Button == MouseButtons.Right) PopupMenu(_listLog, e.Location); };
        body.Controls.Add(_listLog, 0, 6);

        // 行8：状态栏
        _lblStatus = new Label
        {
            Text = "就绪：将 PDF 拖入窗口，或点击「添加 PDF 文件」",
            Dock = DockStyle.Fill,
            TextAlign = ContentAlignment.MiddleLeft,
            Height = 22,
            BackColor = Win95.Face,
        };
        body.Controls.Add(_lblStatus, 0, 7);

        // 窗口级拖拽（拖到任意位置都接收）
        DragEnter += (s, e) => { if (e.Data.GetDataPresent(DataFormats.FileDrop)) e.Effect = DragDropEffects.Copy; };
        DragDrop += (s, e) => AddPaths((string[])e.Data.GetData(DataFormats.FileDrop));
    }

    // ── 添加文件 ─────────────────────────────────
    private void AddFilesDialog()
    {
        using var d = new OpenFileDialog { Title = "选择 PDF 文件（可多选）", Filter = "PDF 文件 (*.pdf)|*.pdf|所有文件 (*.*)|*.*", Multiselect = true };
        if (d.ShowDialog(this) == DialogResult.OK) AddPaths(d.FileNames);
    }

    private void AddDirDialog()
    {
        using var d = new FolderBrowserDialog { Description = "选择包含 PDF 的文件夹" };
        if (d.ShowDialog(this) == DialogResult.OK)
            AddPaths(Directory.GetFiles(d.SelectedPath, "*.pdf"));
    }

    private void AddPaths(string[] paths)
    {
        var existing = _listFiles.Items.Cast<string>().ToHashSet();
        int added = 0;
        foreach (var p in paths)
        {
            if (Directory.Exists(p))
            {
                foreach (var f in Directory.GetFiles(p, "*.pdf"))
                    if (existing.Add(f)) { _listFiles.Items.Add(f); added++; }
            }
            else if (p.EndsWith(".pdf", StringComparison.OrdinalIgnoreCase) && existing.Add(p))
            {
                _listFiles.Items.Add(p);
                added++;
            }
        }
        if (added > 0) _lblStatus.Text = $"已添加 {added} 个 PDF 文件，点击「开始转换」";
        UpdateStatus();
    }

    private void UpdateStatus()
    {
        if (_listFiles.Items.Count > 0)
            _lblStatus.Text = $"已添加 {_listFiles.Items.Count} 个 PDF 文件，点击「开始转换」";
        else
            _lblStatus.Text = "就绪：将 PDF 拖入窗口，或点击「添加 PDF 文件」";
    }

    // ── 转换（后台线程） ──────────────────────────
    private async Task StartConvertAsync()
    {
        var files = _listFiles.Items.Cast<string>().ToList();
        if (files.Count == 0) { MessageBox.Show("请先添加 PDF 文件。", "提示"); return; }

        double zoom = _radio1x.Checked ? 1.0 : _radio3x.Checked ? 3.0 : 2.0;
        string outDir = _editOutdir.Text.Trim();

        _listLog.Items.Clear();
        _logPaths.Clear();
        _progress.Visible = true;
        _progress.Value = 0;
        _progress.Maximum = files.Count;
        _btnConvert.Enabled = false;
        _lblStatus.Text = $"正在转换 ... 共 {files.Count} 个文件";

        int ok = 0, totalJpg = 0;
        await Task.Run(() =>
        {
            foreach (var f in files)
            {
                try
                {
                    var paths = ConvertOne(f, zoom, outDir);
                    ok++;
                    totalJpg += paths.Count;
                    Log($"[OK] {Path.GetFileName(f)} -> {paths.Count} 张", paths);
                }
                catch (Exception ex)
                {
                    Log($"[FAIL] {Path.GetFileName(f)}: {ex.Message}", null);
                }
                BeginInvoke(() => _progress.Value++);
            }
        });

        _progress.Visible = false;
        _btnConvert.Enabled = true;
        _lblStatus.Text = $"完成：{ok} 个 PDF 转换成功，共生成 {totalJpg} 张 JPG。";
        MessageBox.Show($"转换完成！\n{ok} 个 PDF，共生成 {totalJpg} 张 JPG。", "完成");
    }

    private static List<string> ConvertOne(string src, double zoom, string outDir)
    {
        src = Path.GetFullPath(src);
        outDir = string.IsNullOrEmpty(outDir) ? Path.Combine(Path.GetDirectoryName(src), "jpg_output") : outDir;
        Directory.CreateDirectory(outDir);

        var results = new List<string>();
        // PageDimensions 用 DPI 缩放：默认 72 DPI，zoom=2 → 144
        int dpi = (int)Math.Round(72 * zoom);
        using (var doc = DocLib.Instance.GetDocReader(src, new PageDimensions(dpi, dpi)))
        {
            int count = doc.GetPageCount();
            string baseName = Path.GetFileNameWithoutExtension(src);

            for (int i = 0; i < count; i++)
            {
                using var page = doc.GetPageReader(i);
                int w = page.GetPageWidth();
                int h = page.GetPageHeight();
                // GetImage 返回 BGR 字节流
                byte[] bgr = page.GetImage();

                using var bmp = new Bitmap(w, h, System.Drawing.Imaging.PixelFormat.Format24bppRgb);
                var rect = new Rectangle(0, 0, w, h);
                var data = bmp.LockBits(rect, System.Drawing.Imaging.ImageLockMode.WriteOnly, System.Drawing.Imaging.PixelFormat.Format24bppRgb);
                try
                {
                    for (int y = 0; y < h; y++)
                    {
                        IntPtr srcRow = data.Scan0 + y * data.Stride;
                        long srcIdx = (long)y * w * 3;
                        for (int x = 0; x < w; x++)
                        {
                            // BGR → RGB
                            Marshal.WriteByte(srcRow, x * 3, bgr[srcIdx + x * 3 + 2]);
                            Marshal.WriteByte(srcRow, x * 3 + 1, bgr[srcIdx + x * 3 + 1]);
                            Marshal.WriteByte(srcRow, x * 3 + 2, bgr[srcIdx + x * 3]);
                        }
                    }
                }
                finally
                {
                    bmp.UnlockBits(data);
                }

                string name = count == 1 ? $"{baseName}.jpg" : $"{baseName}_p{i + 1}.jpg";
                string path = Path.Combine(outDir, name);
                bmp.Save(path, System.Drawing.Imaging.ImageFormat.Jpeg);
                results.Add(path);
            }
        }
        return results;
    }

    private void Log(string msg, List<string> paths)
    {
        int seq = _logSeq++;
        BeginInvoke(() =>
        {
            _listLog.Items.Add(msg);
            _logPaths[_listLog.Items.Count - 1] = paths ?? new List<string>();
        });
    }

    // ── 右键菜单 ─────────────────────────────────
    private void PopupMenu(ListBox lst, Point location)
    {
        int idx = lst.IndexFromPoint(location);
        if (idx == ListBox.NoMatches) return;
        lst.SelectedIndex = idx; // 高亮反馈

        List<string> paths = lst == _listFiles
            ? new List<string> { (string)lst.SelectedItem }
            : (_logPaths.TryGetValue(idx, out var p) ? p : new List<string>());

        var menu = new ContextMenuStrip { BackColor = Win95.Face, ShowImageMargin = false };
        var mOpen = new ToolStripMenuItem("打开") { Enabled = paths.Count > 0 };
        var mFolder = new ToolStripMenuItem("打开文件夹") { Enabled = paths.Count > 0 };
        var mSave = new ToolStripMenuItem("另存为...") { Enabled = paths.Count > 0 };
        var mDel = new ToolStripMenuItem("删除当前项");
        menu.Items.AddRange(new ToolStripItem[] { mOpen, mFolder, mSave, new ToolStripSeparator(), mDel });

        mOpen.Click += (s, e) => Process.Start(new ProcessStartInfo(paths[0]) { UseShellExecute = true });
        mFolder.Click += (s, e) =>
        {
            if (paths.Count == 1)
                Process.Start("explorer.exe", $"/select,\"{paths[0]}\"");
            else
                Process.Start(new ProcessStartInfo(Path.GetDirectoryName(paths[0])) { UseShellExecute = true });
        };
        mSave.Click += (s, e) => SaveAs(paths[0]);
        mDel.Click += (s, e) =>
        {
            if (lst == _listFiles)
            {
                lst.Items.RemoveAt(idx);
                UpdateStatus();
            }
            else
            {
                _logPaths.Remove(idx);
                lst.Items.RemoveAt(idx);
            }
        };
        menu.Show(lst, location);
    }

    private void SaveAs(string src)
    {
        using var d = new SaveFileDialog
        {
            Title = "另存为",
            FileName = Path.GetFileName(src),
            Filter = "JPG 图片 (*.jpg)|*.jpg|所有文件 (*.*)|*.*",
        };
        if (d.ShowDialog(this) == DialogResult.OK)
        {
            try { File.Copy(src, d.FileName, true); _lblStatus.Text = $"已另存为：{d.FileName}"; }
            catch (Exception ex) { MessageBox.Show(ex.Message, "另存为失败"); }
        }
    }

    // ── 打开输出目录 ──────────────────────────────
    private void OpenOutdir()
    {
        string d = _editOutdir.Text.Trim();
        if (d.Length == 0 && _listFiles.Items.Count > 0)
            d = Path.Combine(Path.GetDirectoryName((string)_listFiles.Items[0])!, "jpg_output");
        if (d.Length > 0 && Directory.Exists(d))
            Process.Start(new ProcessStartInfo(d) { UseShellExecute = true });
    }

    // ── 悬停操作提示（状态栏） ────────────────────
    private void BindHints()
    {
        var hints = new (Control C, string Tip)[]
        {
            (_listFiles, "文件列表 — 右键：打开 / 打开文件夹 / 另存为... / 删除当前项"),
            (_listLog,   "输出列表 — 右键：打开 / 打开文件夹 / 另存为... / 删除当前项"),
            (_btnConvert, "开始转换 — 将 PDF 逐页转为 JPG"),
        };
        foreach (var (c, tip) in hints)
        {
            c.MouseEnter += (s, e) => { _statusBackup = _lblStatus.Text; _lblStatus.Text = tip; };
            c.MouseLeave += (s, e) => _lblStatus.Text = _statusBackup;
        }
    }
}
