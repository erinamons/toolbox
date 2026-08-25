// Win95.cs — Win95 视觉风格辅助
// 思路：Program 不开 EnableVisualStyles，控件走经典渲染；
//      这里再统一刷灰底、给按钮画凸起边框。
using System.Reflection;
using System.Runtime.InteropServices;

namespace ToolboxCS;

public static class Win95
{
    public static readonly Color Face = Color.FromArgb(192, 192, 192);
    public static readonly Color Light = Color.White;
    public static readonly Color Shadow = Color.FromArgb(128, 128, 128);
    public static readonly Color DarkShadow = Color.Black;
    public static readonly Color Navy = Color.FromArgb(0, 0, 128);
    public static readonly Color NavyLight = Color.FromArgb(16, 132, 208);

    public const int Raised = 0;
    public const int Sunken = 1;
    public const int RaisedHot = 2;

    /// <summary>递归把容器内所有控件刷成 Win95 观感。</summary>
    public static void Apply(Control root)
    {
        foreach (Control c in root.Controls)
        {
            switch (c)
            {
                case Button b:
                    StyleButton(b);
                    break;
                case RadioButton rb:
                    rb.BackColor = Face;
                    rb.FlatStyle = FlatStyle.Standard; // 经典模式自带圆点
                    break;
                case CheckBox cb:
                    cb.BackColor = Face;
                    cb.FlatStyle = FlatStyle.Standard;
                    break;
                case Label lbl:
                    lbl.BackColor = Face;
                    break;
            }
            // 容器递归（含 TableLayout/FlowLayout/普通 Panel）
            if (c.HasChildren) Apply(c);
        }
    }

    /// <summary>经典凸起按钮（push button 观感：浅白高光 + 灰黑阴影）。</summary>
    public static void StyleButton(Button b)
    {
        b.BackColor = Face;
        b.ForeColor = Color.Black;
        b.FlatStyle = FlatStyle.Flat;
        b.FlatAppearance.BorderSize = 0;
        b.FlatAppearance.MouseOverBackColor = Face;
        b.FlatAppearance.MouseDownBackColor = Face;
        b.Cursor = Cursors.Hand;
        b.Height = Math.Max(b.Height, 26);
        b.Paint += ButtonPaint;
    }

    private static void ButtonPaint(object? sender, PaintEventArgs e)
    {
        var b = (Button)sender!;
        bool pressed = Control.MouseButtons == MouseButtons.Left && b.Capture;
        DrawBorder(e.Graphics, b.ClientRectangle, pressed ? Sunken : Raised);

        // 文字（按下位移 1px，正宗手感）
        var flags = TextFormatFlags.HorizontalCenter | TextFormatFlags.VerticalCenter |
                    TextFormatFlags.SingleLine | TextFormatFlags.EndEllipsis;
        if (pressed) flags |= 0;
        var rect = b.ClientRectangle;
        if (pressed) rect.Offset(1, 1);
        if (!b.Enabled)
            TextRenderer.DrawText(e.Graphics, b.Text, b.Font, rect.OffsetBy(1, 1), Color.White, flags);
        TextRenderer.DrawText(e.Graphics, b.Text, b.Font, rect,
            b.Enabled ? Color.Black : Color.Gray, flags);
    }

    private static Rectangle OffsetBy(this Rectangle r, int dx, int dy) => new(r.X + dx, r.Y + dy, r.Width, r.Height);

    /// <summary>双色 3D 边框。</summary>
    public static void DrawBorder(Graphics g, Rectangle rect, int style)
    {
        int x0 = rect.X, y0 = rect.Y, x1 = rect.Right - 1, y1 = rect.Bottom - 1;
        using var penLight = new Pen(Light);
        using var penShadow = new Pen(Shadow);

        switch (style)
        {
            case Raised:
                g.DrawLine(penLight, x0, y0, x1, y0); g.DrawLine(penLight, x0, y0, x0, y1);
                g.DrawLine(penShadow, x1, y0, x1, y1); g.DrawLine(penShadow, x0, y1, x1, y1);
                g.DrawLine(Pens.White, x0 + 1, y0 + 1, x1 - 1, y0 + 1); g.DrawLine(Pens.White, x0 + 1, y0 + 1, x0 + 1, y1 - 1);
                g.DrawLine(Pens.Black, x1 - 1, y0 + 1, x1 - 1, y1 - 1); g.DrawLine(Pens.Black, x0 + 1, y1 - 1, x1 - 1, y1 - 1);
                break;
            case Sunken:
                g.DrawLine(Pens.Black, x0, y0, x1, y0); g.DrawLine(Pens.Black, x0, y0, x0, y1);
                g.DrawLine(penShadow, x0 + 1, y0 + 1, x1 - 1, y0 + 1); g.DrawLine(penShadow, x0 + 1, y0 + 1, x0 + 1, y1 - 1);
                g.DrawLine(Pens.White, x1, y0, x1, y1); g.DrawLine(Pens.White, x0, y1, x1, y1);
                g.DrawLine(Pens.White, x1 - 1, y0 + 1, x1 - 1, y1 - 1); g.DrawLine(Pens.White, x0 + 1, y1 - 1, x1 - 1, y1 - 1);
                break;
            case RaisedHot:
                g.DrawLine(penLight, x0, y0, x1, y0); g.DrawLine(penLight, x0, y0, x0, y1);
                g.DrawLine(penShadow, x1, y0, x1, y1); g.DrawLine(penShadow, x0, y1, x1, y1);
                using (var hot = new Pen(NavyLight))
                {
                    g.DrawLine(hot, x0 + 1, y0 + 1, x1 - 1, y0 + 1); g.DrawLine(hot, x0 + 1, y0 + 1, x0 + 1, y1 - 1);
                    g.DrawLine(hot, x1 - 1, y0 + 1, x1 - 1, y1 - 1); g.DrawLine(hot, x0 + 1, y1 - 1, x1 - 1, y1 - 1);
                }
                break;
        }
    }

    /// <summary>给任意控件画凸起边框（卡片用）。</summary>
    public static void Border3D(Control c, int style)
    {
        var g = c.CreateGraphics();
        DrawBorder(g, c.ClientRectangle, style);
        g.Dispose();
    }

    // ── Win32: 获取经典主题下的按钮尺寸 ────────────
    [DllImport("uxtheme.dll", SetLastError = true)]
    private static extern int SetWindowTheme(IntPtr hWnd, string? pszSubAppName, string? pszSubIdList);

    /// <summary>把 ListBox/TextBox 等设为经典主题（" explorer 风格 → 经典"）。</summary>
    public static void ClassicTheme(Control c)
    {
        if (c.IsHandleCreated)
            _ = SetWindowTheme(c.Handle, null, null);
        else
            c.HandleCreated += (s, e) => _ = SetWindowTheme(c.Handle, null, null);
    }
}
