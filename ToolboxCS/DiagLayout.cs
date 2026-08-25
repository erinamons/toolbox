// DiagLayout.cs — 测量工具页各控件位置，检测对齐问题
using System.Text;

namespace ToolboxCS;

internal static class DiagLayout
{
    [STAThread]
    private static void Main()
    {
        Application.SetHighDpiMode(HighDpiMode.SystemAware);
        Application.SetCompatibleTextRenderingDefault(false);

        var form = new Pdf2JpgForm();
        form.Show();
        Application.DoEvents();

        var sb = new StringBuilder();
        Walk(form, 0, sb);
        File.WriteAllText("layout_report.txt", sb.ToString(), Encoding.UTF8);

        // 检查行内对齐：同一行的控件 Top 应接近
        form.Close();
    }

    private static void Walk(Control c, int depth, StringBuilder sb)
    {
        string indent = new(' ', depth * 2);
        string text = c is Button b ? b.Text : c is Label l ? l.Text : "";
        sb.AppendLine($"{indent}{c.GetType().Name} pos=({c.Left},{c.Top}) size={c.Width}x{c.Height} '{Trunc(text, 20)}'");
        foreach (Control child in c.Controls)
            Walk(child, depth + 1, sb);
    }

    private static string Trunc(string s, int n) => s.Length <= n ? s : s[..n];
}
