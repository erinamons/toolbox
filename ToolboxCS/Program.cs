// Program.cs — 入口
// 关键：不调用 EnableVisualStyles → comctl32 v5 经典渲染，所有控件自动变 Win95 观感
namespace ToolboxCS;

internal static class Program
{
    [STAThread]
    private static void Main()
    {
        Application.SetHighDpiMode(HighDpiMode.SystemAware);
        Application.SetCompatibleTextRenderingDefault(false);
        Application.Run(new MainForm());
    }
}
