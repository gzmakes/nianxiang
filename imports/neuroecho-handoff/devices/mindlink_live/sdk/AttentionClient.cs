// .NET 6+ console example. Windows app/Unity integration can reuse the HTTP contract.
using System;
using System.Net.Http;
using System.Text.Json;
using System.Threading.Tasks;
using System.Diagnostics;
class Program {
 static async Task Main() {
  using var client = new HttpClient { Timeout=TimeSpan.FromSeconds(2) };
  var hold=new Stopwatch();bool showing=false;
  while(true) {
   try {
    using var doc=JsonDocument.Parse(await client.GetStringAsync("http://127.0.0.1:8876/api/v1/state"));
    var root=doc.RootElement;var a=root.GetProperty("attention");
    bool valid=root.GetProperty("live").GetBoolean() && a.GetProperty("valid").GetBoolean()
       && a.GetProperty("age_ms").ValueKind==JsonValueKind.Number && a.GetProperty("age_ms").GetDouble()<=2500;
    if(!valid){hold.Reset();showing=false;Console.WriteLine("HIDE_CONTENT");Console.WriteLine("Signal unavailable");}
    else {
     double score=a.GetProperty("value").GetDouble();
     if(score>=60){if(!hold.IsRunning)hold.Start();if(!showing&&hold.Elapsed.TotalSeconds>=2){showing=true;Console.WriteLine("SHOW_CONTENT");}}
     else {hold.Reset();if(score<45){showing=false;Console.WriteLine("HIDE_CONTENT");}}
    }
   } catch(Exception e) when(e is HttpRequestException || e is TaskCanceledException || e is JsonException) {
    hold.Reset();showing=false;Console.WriteLine("HIDE_CONTENT");Console.WriteLine("Service unavailable");
   }
   await Task.Delay(250);
  }
 }
}
