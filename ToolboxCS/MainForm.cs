// MainForm.cs — 工具箱首页（Win95 风格）
namespace ToolboxCS;

public class MainForm : Form
{
    /// <summary>从 exe 内嵌资源取图标。</summary>
    internal static Icon AppIcon
    {
        get
        {
            try
            {
                using var ms = typeof(MainForm).Assembly.GetManifestResourceStream("ToolboxCS.toolbox.ico");
                return ms != null ? new Icon(ms) : SystemIcons.Application;
            }
            catch
            {
                return SystemIcons.Application;
            }
        }
    }

    internal static Image LoadPng()
    {
        using var ms = typeof(MainForm).Assembly.GetManifestResourceStream("ToolboxCS.pdf.png");
        return Image.FromStream(ms!);
    }

    private readonly Panel _cardHost;

    public MainForm()
    {
        Text = "工具箱";
        Icon = AppIcon;
        ClientSize = new Size(620, 480);
        MinimumSize = new Size(560, 420 + 39);
        StartPosition = FormStartPosition.CenterScreen;
        Font = new Font("Microsoft YaHei UI", 9F);
        BackColor = Win95.Face;

        // ── 菜单栏（装饰） ─────────────────────────
        var menu = new Label
        {
            Text = "文件(F)    帮助(H)",
            Dock = DockStyle.Top,
            Height = 24,
            TextAlign = ContentAlignment.MiddleLeft,
            Padding = new Padding(6, 3, 0, 0),
            BackColor = Win95.Face,
        };
        Controls.Add(menu);

        // ── 工具卡片区 ─────────────────────────────
        _cardHost = new Panel
        {
            Dock = DockStyle.Fill,
            AutoScroll = true,
            BackColor = Win95.Face,
            Padding = new Padding(8),
        };
        Controls.Add(_cardHost);
        _cardHost.BringToFront();

        BuildCards();
        Win95.Apply(this);
    }

    private void BuildCards()
    {
        (string Name, string Desc, Type FormType)[] tools =
        {
            ("PDF 转 JPG", "把 PDF 每页转换为 JPG 图片", typeof(Pdf2JpgForm)),
        };

        int y = 8;
        foreach (var t in tools)
        {
            var card = MakeCard(t.Name, t.Desc, t.FormType);
            card.Location = new Point(8, y);
            _cardHost.Controls.Add(card);
            y += card.Height + 10;
        }

        // 底部状态栏（凹陷）
        var status = new Label
        {
            Text = $"已安装 {tools.Length} 个工具",
            Dock = DockStyle.Bottom,
            Height = 24,
            TextAlign = ContentAlignment.MiddleLeft,
            Padding = new Padding(6, 4, 0, 0),
            BackColor = Win95.Face,
        };
        status.Paint += (s, e) => Win95.DrawBorder(e.Graphics, status.ClientRectangle, Win95.Sunken);
        Controls.Add(status);
    }

    private Control MakeCard(string name, string desc, Type formType)
    {
        var card = new Panel
        {
            Size = new Size(580, 64),
            BackColor = Win95.Face,
            Cursor = Cursors.Hand,
        };

        var icon = new PictureBox
        {
            Image = LoadPng(),
            SizeMode = PictureBoxSizeMode.Zoom,
            Location = new Point(12, 12),
            Size = new Size(40, 40),
        };
        card.Controls.Add(icon);

        var lbl = new Label
        {
            Text = name,
            Font = new Font("Microsoft YaHei UI", 11F, FontStyle.Bold),
            Location = new Point(66, 12),
            AutoSize = true,
        };
        card.Controls.Add(lbl);

        var lbl2 = new Label
        {
            Text = desc,
            ForeColor = Color.FromArgb(64, 64, 64),
            Location = new Point(66, 40),
            AutoSize = true,
        };
        card.Controls.Add(lbl2);

        void Open()
        {
            var frm = (Form)Activator.CreateInstance(formType);
            frm.Show(this);
        }

        card.Paint += (s, e) =>
        {
            bool hot = card.ClientRectangle.Contains(card.PointToClient(Cursor.Position));
            Win95.DrawBorder(e.Graphics, card.ClientRectangle, hot ? Win95.RaisedHot : Win95.Raised);
        };
        card.MouseEnter += (s, e) => card.Invalidate();
        card.MouseLeave += (s, e) => card.Invalidate();
        card.MouseDown += (s, e) =>
        {
            if (e.Button == MouseButtons.Left)
            {
                using var g = card.CreateGraphics();
                Win95.DrawBorder(g, card.ClientRectangle, Win95.Sunken);
            }
        };
        card.MouseUp += (s, e) =>
        {
            if (e.Button == MouseButtons.Left && card.ClientRectangle.Contains(card.PointToClient(Cursor.Position)))
                Open();
            card.Invalidate();
        };
        foreach (Control c in card.Controls)
        {
            c.Cursor = Cursors.Hand;
            c.Click += (s, e) => Open();
        }
        return card;
    }
}
