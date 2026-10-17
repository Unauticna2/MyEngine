// Built by Windows PowerShell/.NET Framework, on a dedicated STA process.
using System;
using System.Collections.Generic;
using System.IO;
using System.Runtime.InteropServices;
using System.Text;
using System.Web.Script.Serialization;
using System.Windows;
using System.Windows.Controls;
using System.Windows.Interop;
using System.Windows.Media;
using System.Windows.Threading;

public sealed class MyEngineVideoHost {
    [DllImport("user32.dll")] static extern bool IsWindow(IntPtr h);
    [DllImport("user32.dll")] static extern bool SetWindowPos(IntPtr h,IntPtr after,int x,int y,int w,int height,uint flags);
    [DllImport("user32.dll")] static extern bool ShowWindow(IntPtr h,int cmd);
    [DllImport("gdi32.dll")] static extern IntPtr CreateRectRgn(int l,int t,int r,int b);
    [DllImport("gdi32.dll")] static extern bool DeleteObject(IntPtr obj);
    [DllImport("user32.dll")] static extern int SetWindowRgn(IntPtr h,IntPtr region,bool redraw);
    [DllImport("user32.dll")] static extern IntPtr GetWindowDpiAwarenessContext(IntPtr h);
    [DllImport("user32.dll")] static extern IntPtr SetThreadDpiAwarenessContext(IntPtr context);
    readonly JavaScriptSerializer json=new JavaScriptSerializer();
    string path; string status; string state="loading"; bool ended; bool playing; bool loop; int restart;
    HwndSource source; MediaElement media; Grid root; IntPtr parent;
    DispatcherTimer timer; DateTime lastWrite=DateTime.MinValue;
    Dictionary<string,object> cfg;
    static int N(object value) {return Convert.ToInt32(value);}
    static bool B(Dictionary<string,object> d,string key) {return d.ContainsKey(key)&&Convert.ToBoolean(d[key]);}
    void Report(string value,string error) {
        state=value;
        try {
            string temp=status+".tmp";
            File.WriteAllText(temp,json.Serialize(new {state=value,error=error}),new UTF8Encoding(false));
            if(File.Exists(status)) File.Replace(temp,status,null); else File.Move(temp,status);
        } catch(IOException) { }
    }
    void Apply() {
        if(B(cfg,"close")||!IsWindow(parent)) {Finish();return;}
        var r=(System.Collections.IList)cfg["rect"];var clip=(System.Collections.IList)cfg["clip"];
        int x=N(r[0]),y=N(r[1]),w=Math.Max(1,N(r[2])),h=Math.Max(1,N(r[3]));
        SetWindowPos(source.Handle,IntPtr.Zero,x,y,w,h,0x14); // NOACTIVATE | NOZORDER
        Matrix m=source.CompositionTarget.TransformFromDevice;
        root.Width=w*m.M11;root.Height=h*m.M22;
        IntPtr region=CreateRectRgn(N(clip[0]),N(clip[1]),N(clip[2]),N(clip[3]));
        if(SetWindowRgn(source.Handle,region,true)==0)DeleteObject(region);
        bool visible=B(cfg,"visible");ShowWindow(source.Handle,visible?5:0);
        loop=B(cfg,"loop");media.Volume=Convert.ToDouble(cfg["volume"]);
        bool wanted=visible&&B(cfg,"playing");
        int requested=cfg.ContainsKey("restart")?N(cfg["restart"]):0;
        if(requested!=restart){restart=requested;media.Position=TimeSpan.Zero;ended=false;playing=false;}
        if(wanted!=playing) {
            if(wanted) {if(ended){media.Position=TimeSpan.Zero;ended=false;} media.Play();Report("playing",null);}
            else {media.Pause();Report("paused",null);}
            playing=wanted;
        }
    }
    void Tick(object sender,EventArgs args) {
        if(!IsWindow(parent)){Finish();return;}
        try {
            DateTime write=File.GetLastWriteTimeUtc(path);
            if(write!=lastWrite){cfg=json.Deserialize<Dictionary<string,object>>(File.ReadAllText(path,Encoding.UTF8));lastWrite=write;Apply();}
        } catch(IOException) { } catch(Exception e) {Report("error",e.Message);}
    }
    void Finish() {
        timer.Stop();media.Close();source.Dispose();Dispatcher.CurrentDispatcher.BeginInvokeShutdown(DispatcherPriority.Normal);
    }
    void Start(string control) {
        path=control;status=Path.Combine(Path.GetDirectoryName(path),"status.json");
        cfg=json.Deserialize<Dictionary<string,object>>(File.ReadAllText(path,Encoding.UTF8));
        parent=new IntPtr(Convert.ToInt64(cfg["parent"]));
        if(!IsWindow(parent))throw new InvalidOperationException("Video parent window does not exist");
        SetThreadDpiAwarenessContext(GetWindowDpiAwarenessContext(parent));
        var p=new HwndSourceParameters("MyEngine video");p.ParentWindow=parent;p.WindowStyle=0x42000000;p.ExtendedWindowStyle=0x08000000;p.Width=1;p.Height=1;
        source=new HwndSource(p);root=new Grid();root.Background=Brushes.Black;
        media=new MediaElement();media.LoadedBehavior=MediaState.Manual;media.UnloadedBehavior=MediaState.Manual;
        media.Stretch=(string)cfg["fit"]=="stretch"?Stretch.Fill:(string)cfg["fit"]=="fill"?Stretch.UniformToFill:Stretch.Uniform;
        root.Children.Add(media);source.RootVisual=root;
        media.MediaOpened+=delegate {Report(playing?"playing":"paused",null);};
        media.MediaFailed+=delegate(object s,ExceptionRoutedEventArgs e){Report("error",e.ErrorException.Message);};
        media.MediaEnded+=delegate {if(loop){media.Position=TimeSpan.Zero;media.Play();}else {ended=true;Report("ended",null);}};
        media.Source=new Uri((string)cfg["source"],UriKind.Absolute);
        timer=new DispatcherTimer();timer.Interval=TimeSpan.FromMilliseconds(50);timer.Tick+=Tick;
        Report("ready",null);Apply();timer.Start();Dispatcher.Run();
    }
    public static void Run(string path) {new MyEngineVideoHost().Start(path);}
}
