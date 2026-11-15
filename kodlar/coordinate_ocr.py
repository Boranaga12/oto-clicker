"""A single persistent Windows OCR process; no cloud or Python dependencies."""
from __future__ import annotations

import base64
import gzip
import json
import os
import queue
import subprocess
import threading
import time
import re

from .position_model import parse_coordinates
from .glyph_ocr import GlyphReader


def ocr_error_message(error):
    text = str(error).strip()
    lowered = text.casefold()
    if 'ocr language' in lowered or 'ocr dili' in lowered or 'recognizer language' in lowered:
        return ('Windows OCR dili bulunamadı. Windows dil ayarlarından OCR destekli '
                'bir dilin Metin Tanıma bileşenini yükleyin; ardından Yeniden Dene kullanın.')
    if isinstance(error, FileNotFoundError):
        return 'Windows PowerShell bulunamadı; Windows bileşenlerini kontrol edin.'
    if any(word in lowered for word in ('denied', 'blocked', 'policy', 'engellen', '0x80070005', 'language mode', 'constrainedlanguage')):
        return 'Windows OCR yardımcısı engellendi; Windows güvenlik veya kurum ilkelerini kontrol edin.'
    return 'Windows OCR başlatılamadı. Yeniden Dene ile tekrar deneyin; aşağıdaki ayrıntıyı kontrol edin.'


SCRIPT = r'''
$ErrorActionPreference = 'Stop'
[Console]::InputEncoding = New-Object System.Text.UTF8Encoding($false)
[Console]::OutputEncoding = New-Object System.Text.UTF8Encoding($false)
try {
 Add-Type -AssemblyName System.Runtime.WindowsRuntime
 Add-Type -AssemblyName System.Drawing
 $null = [Windows.Media.Ocr.OcrEngine, Windows.Foundation, ContentType=WindowsRuntime]
 $null = [Windows.Graphics.Imaging.BitmapDecoder, Windows.Foundation, ContentType=WindowsRuntime]
 $null = [Windows.Storage.Streams.InMemoryRandomAccessStream, Windows.Foundation, ContentType=WindowsRuntime]
 $null = [Windows.Storage.Streams.DataWriter, Windows.Foundation, ContentType=WindowsRuntime]
 $null = [Windows.Globalization.Language, Windows.Foundation, ContentType=WindowsRuntime]
 $asTask = [System.WindowsRuntimeSystemExtensions].GetMethods() | Where-Object {
   $_.Name -eq 'AsTask' -and $_.IsGenericMethod -and $_.GetParameters().Count -eq 1 -and
   $_.GetParameters()[0].ParameterType.Name -eq 'IAsyncOperation`1'
 } | Select-Object -First 1
 function Await($operation, [Type]$type) {
   $task = $asTask.MakeGenericMethod($type).Invoke($null, @($operation))
   if (-not $task.Wait(2500)) { throw 'OCR operation timed out' }
   return $task.GetAwaiter().GetResult()
 }
 $language = New-Object -TypeName Windows.Globalization.Language -ArgumentList 'en-US'
 $engine = $null
 if ([Windows.Media.Ocr.OcrEngine]::IsLanguageSupported($language)) {
  $engine = [Windows.Media.Ocr.OcrEngine]::TryCreateFromLanguage($language)
 }
 if ($null -eq $engine) { $engine = [Windows.Media.Ocr.OcrEngine]::TryCreateFromUserProfileLanguages() }
 if ($null -eq $engine) {
  foreach ($installedLanguage in [Windows.Media.Ocr.OcrEngine]::AvailableRecognizerLanguages) {
   $engine = [Windows.Media.Ocr.OcrEngine]::TryCreateFromLanguage($installedLanguage)
   if ($null -ne $engine) { break }
  }
 }
 Add-Type -ReferencedAssemblies System.Drawing,System.Core -TypeDefinition @'
using System;
using System.Drawing;
using System.Drawing.Imaging;
using System.Drawing.Drawing2D;
using System.IO;
using System.Runtime.InteropServices;
using System.Collections.Generic;
public static class CoordinateFrames {
 public class Batch { public string[] Frames; public int[][] Shapes; public string Pixels; public string Snapshot; }
 [DllImport("user32.dll")] static extern bool SetProcessDpiAwarenessContext(IntPtr context);
 [DllImport("user32.dll")] static extern IntPtr SetThreadDpiAwarenessContext(IntPtr context);
 [DllImport("user32.dll")] static extern IntPtr GetDC(IntPtr window);
 [DllImport("user32.dll")] static extern int ReleaseDC(IntPtr window,IntPtr dc);
 [DllImport("gdi32.dll")] static extern bool BitBlt(IntPtr destination,int dx,int dy,int width,int height,IntPtr source,int sx,int sy,uint operation);
 static CoordinateFrames() {
  try { SetProcessDpiAwarenessContext(new IntPtr(-4)); } catch(EntryPointNotFoundException) { }
 }
 public static Batch Make(int x, int y, int w, int h, string image, int[] preferred, bool pixelsOnly) {
  try { SetThreadDpiAwarenessContext(new IntPtr(-4)); } catch(EntryPointNotFoundException) { }
  using (Bitmap source = new Bitmap(w,h,PixelFormat.Format32bppArgb)) {
   using (Graphics g = Graphics.FromImage(source)) {
    if (String.IsNullOrEmpty(image)) {
     IntPtr desktop=GetDC(IntPtr.Zero),target=IntPtr.Zero;
     try {
      target=g.GetHdc();
      if(desktop==IntPtr.Zero || !BitBlt(target,0,0,w,h,desktop,x,y,0x40CC0020))
       throw new InvalidOperationException("Desktop coordinate capture failed");
     } finally {
      if(target!=IntPtr.Zero) g.ReleaseHdc(target);
      if(desktop!=IntPtr.Zero) ReleaseDC(IntPtr.Zero,desktop);
     }
    }
    else using (MemoryStream stream = new MemoryStream(Convert.FromBase64String(image)))
     using (Bitmap input = new Bitmap(stream)) g.DrawImage(input,new Rectangle(0,0,w,h),new Rectangle(x,y,w,h),GraphicsUnit.Pixel);
   }
   byte[] neutral=new byte[w*h];
   BitmapData raw=source.LockBits(new Rectangle(0,0,w,h),ImageLockMode.ReadOnly,PixelFormat.Format32bppArgb);
   byte[] colors=new byte[w*h*4];
   try { Marshal.Copy(raw.Scan0,colors,0,colors.Length); } finally {source.UnlockBits(raw);}
   for(int i=0;i<neutral.Length;i++) {
    int at=i*4,lo=Math.Min(colors[at],Math.Min(colors[at+1],colors[at+2]));
    int hi=Math.Max(colors[at],Math.Max(colors[at+1],colors[at+2]));
    neutral[i]=(byte)(hi-lo<=65 ? lo : 0);
   }
   string pixels=Convert.ToBase64String(neutral);
   if(pixelsOnly) {
    using(MemoryStream snapshot=new MemoryStream()) {
     source.Save(snapshot,ImageFormat.Png);
     return new Batch {Pixels=pixels, Snapshot=Convert.ToBase64String(snapshot.ToArray())};
    }
   }
   List<string> frames = new List<string>();
   List<int[]> shapes = new List<int[]>();
   HashSet<int> selected=preferred!=null && preferred.Length>=2 ? new HashSet<int>(preferred) : null;
   AddFrame(frames,selected,source,false,4);
   foreach(int threshold in new int[]{165,145,125})
   using (Bitmap mask = new Bitmap(w,h,PixelFormat.Format32bppArgb)) {
    Rectangle rect = new Rectangle(0,0,w,h);
    BitmapData src = source.LockBits(rect,ImageLockMode.ReadOnly,PixelFormat.Format32bppArgb);
    byte[] data = new byte[w*h*4];
    try { Marshal.Copy(src.Scan0,data,0,data.Length); } finally { source.UnlockBits(src); }
    for(int i=0;i<data.Length;i+=4) {
     int hi=Math.Max(data[i],Math.Max(data[i+1],data[i+2]));
     int lo=Math.Min(data[i],Math.Min(data[i+1],data[i+2]));
     byte value=(byte)(lo>=threshold && hi-lo<=65 ? 0 : 255);
     data[i]=data[i+1]=data[i+2]=value; data[i+3]=255;
    }
    BitmapData dst=mask.LockBits(rect,ImageLockMode.WriteOnly,PixelFormat.Format32bppArgb);
    try { Marshal.Copy(data,0,dst.Scan0,data.Length); } finally { mask.UnlockBits(dst); }
    if(threshold>=145) shapes.Add(Holes(mask));
    AddFrame(frames,selected,mask,true,4,true);
    AddFrame(frames,selected,mask,true,4);
    AddFrame(frames,selected,mask,true,6);
   }
   // Status panels are often selected with their border. Extract the bright
   // text row before OCR instead of asking OCR to parse the entire panel.
   using(Bitmap band=TextBand(source)) {
    AddFrame(frames,selected,band,false,4);
    AddFrame(frames,selected,band,false,6);
    using(Bitmap negative=new Bitmap(band.Width,band.Height,PixelFormat.Format32bppArgb)) {
     for(int py=0;py<band.Height;py++) for(int px=0;px<band.Width;px++) {
      Color c=band.GetPixel(px,py);
      int grey=(c.R*299+c.G*587+c.B*114)/1000;
      int value=Math.Min(255,Math.Max(0,(210-grey)*2));
      negative.SetPixel(px,py,Color.FromArgb(value,value,value));
     }
     AddFrame(frames,selected,negative,true,4);
     AddFrame(frames,selected,negative,true,6);
    }
   }
   return new Batch {Frames=frames.ToArray(), Shapes=shapes.ToArray(), Pixels=pixels};
  }
 }
 static void AddFrame(List<string> frames,HashSet<int> selected,Bitmap source,bool mask,int scale,bool reinforce=false) {
  frames.Add(selected==null || selected.Contains(frames.Count) ? Encode(source,mask,scale,reinforce) : null);
 }
 static Bitmap TextBand(Bitmap source) {
  int first=-1,bestTop=0,bestBottom=source.Height-1,bestScore=0,sum=0;
  for(int y=0;y<=source.Height;y++) {
   int count=0;
   if(y<source.Height) for(int x=0;x<source.Width;x++) {
    Color c=source.GetPixel(x,y);
    int lo=Math.Min(c.R,Math.Min(c.G,c.B)),hi=Math.Max(c.R,Math.Max(c.G,c.B));
    if(lo>=145 && hi-lo<=65) count++;
   }
   if(count>=Math.Max(2,source.Width/50)) {
    if(first<0) first=y;
    sum+=count;
   } else if(first>=0) {
    int height=y-first;
    if(height>=5 && height<=40 && sum<height*source.Width*.65 && sum>bestScore) {
     bestTop=Math.Max(0,first-2);bestBottom=Math.Min(source.Height-1,y+1);bestScore=sum;
    }
    first=-1;sum=0;
   }
  }
  return source.Clone(new Rectangle(0,bestTop,source.Width,bestBottom-bestTop+1),PixelFormat.Format32bppArgb);
 }
 static int[] Holes(Bitmap mask) {
  int w=mask.Width,h=mask.Height;
  bool[] visited=new bool[w*h];
  List<int[]> boxes=new List<int[]>();
  Queue<int> queue=new Queue<int>();
  for(int y=0;y<h;y++) for(int x=0;x<w;x++) {
   int at=y*w+x;
   if(visited[at] || mask.GetPixel(x,y).R!=0) continue;
   int left=x,right=x,top=y,bottom=y;
   visited[at]=true;queue.Enqueue(at);
   while(queue.Count>0) {
    int p=queue.Dequeue(),px=p%w,py=p/w;
    left=Math.Min(left,px);right=Math.Max(right,px);top=Math.Min(top,py);bottom=Math.Max(bottom,py);
    for(int dy=-1;dy<=1;dy++) for(int dx=-1;dx<=1;dx++) {
     int nx=px+dx,ny=py+dy;
     if(nx<0 || ny<0 || nx>=w || ny>=h) continue;
     int n=ny*w+nx;
     if(!visited[n] && mask.GetPixel(nx,ny).R==0) {visited[n]=true;queue.Enqueue(n);}
    }
   }
   if(bottom-top>=4 && right-left>=1) boxes.Add(new int[]{left,top,right,bottom});
  }
  boxes.Sort((a,b)=>a[0].CompareTo(b[0]));
  List<int> result=new List<int>();
  foreach(int[] box in boxes) {
   int bw=box[2]-box[0]+1,bh=box[3]-box[1]+1,holes=0;
   bool[] seen=new bool[bw*bh];
   for(int y=0;y<bh;y++) for(int x=0;x<bw;x++) {
    int at=y*bw+x;
    if(seen[at] || mask.GetPixel(box[0]+x,box[1]+y).R==0) continue;
    bool boundary=false;queue.Enqueue(at);seen[at]=true;
    while(queue.Count>0) {
     int p=queue.Dequeue(),px=p%bw,py=p/bw;
     if(px==0 || py==0 || px==bw-1 || py==bh-1) boundary=true;
     foreach(int step in new int[]{-1,1,-bw,bw}) {
      int n=p+step;
      if(n<0 || n>=bw*bh || (Math.Abs(step)==1 && Math.Abs(n%bw-px)!=1)) continue;
      if(!seen[n] && mask.GetPixel(box[0]+n%bw,box[1]+n/bw).R!=0) {seen[n]=true;queue.Enqueue(n);}
     }
    }
    if(!boundary) holes++;
   }
   result.Add(holes);
  }
  return result.ToArray();
 }
 static string Encode(Bitmap source, bool mask, int scale, bool reinforce=false) {
  using(Bitmap scaled=new Bitmap(source.Width*scale+32,source.Height*scale+32,PixelFormat.Format32bppArgb)) {
   using(Graphics g=Graphics.FromImage(scaled)) {
    g.Clear(mask ? Color.White : Color.Black);
    g.InterpolationMode=InterpolationMode.HighQualityBicubic;
    g.PixelOffsetMode=PixelOffsetMode.Half;
    g.DrawImage(source,new Rectangle(16,16,source.Width*scale,source.Height*scale));
   }
   if(reinforce) {
    // One enlarged pixel is at most a quarter of an original pixel.
    // Preserve decimal dots without eroding or closing original glyph holes.
    int width=scaled.Width, height=scaled.Height;
    BitmapData bits=scaled.LockBits(new Rectangle(0,0,width,height),ImageLockMode.ReadWrite,PixelFormat.Format32bppArgb);
    byte[] original=new byte[width*height*4];
    try {
     Marshal.Copy(bits.Scan0,original,0,original.Length);
     byte[] enhanced=(byte[])original.Clone();
     for(int y=1;y<height-1;y++) for(int x=1;x<width-1;x++) {
      int at=(y*width+x)*4;
      byte value=original[at];
      for(int dy=-1;dy<=1;dy++) for(int dx=-1;dx<=1;dx++)
       value=Math.Min(value,original[((y+dy)*width+x+dx)*4]);
      enhanced[at]=enhanced[at+1]=enhanced[at+2]=value;
     }
     Marshal.Copy(enhanced,0,bits.Scan0,enhanced.Length);
    } finally { scaled.UnlockBits(bits); }
   }
   using(MemoryStream stream=new MemoryStream()) {
    scaled.Save(stream,ImageFormat.Png); return Convert.ToBase64String(stream.ToArray());
   }
  }
 }
}
'@
 [Console]::WriteLine((@{ready=$true; ocr_available=($null -ne $engine)} | ConvertTo-Json -Compress))
 $lastBatch=$null; $lastCaptureId=0; $captureTimer=$null
 while ($null -ne ($line = [Console]::ReadLine())) {
  try {
   $request = $line | ConvertFrom-Json
   $r = $request.region
   if ($r.Count -ne 4 -or $r[2] -lt 8 -or $r[2] -gt 640 -or $r[3] -lt 8 -or $r[3] -gt 180) { throw 'Invalid coordinate region' }
   if($request.mode -eq 'capture') {
    $captureTimer = [System.Diagnostics.Stopwatch]::StartNew()
    $lastBatch = [CoordinateFrames]::Make($r[0],$r[1],$r[2],$r[3],$request.image,$null,$true)
    $lastCaptureId=$request.id
    [Console]::WriteLine((@{id=$request.id; pixels=$lastBatch.Pixels; age_ms=$captureTimer.Elapsed.TotalMilliseconds} | ConvertTo-Json -Compress))
    continue
   }
   if($null -eq $lastBatch -or $request.capture_id -ne $lastCaptureId) {throw 'Stale coordinate capture'}
   if($null -eq $engine) {throw 'Windows OCR language is not installed'}
   $batch = [CoordinateFrames]::Make(0,0,$r[2],$r[3],$lastBatch.Snapshot,[int[]]$request.preferred,$false)
   $frames = $batch.Frames
   $texts = @()
   $indices = @(0..($frames.Length-1))
   if ($request.preferred -and $request.preferred.Count -ge 2) { $indices = @($request.preferred) }
   foreach ($index in $indices) {
    $frame = $frames[$index]
    $stream = New-Object -TypeName Windows.Storage.Streams.InMemoryRandomAccessStream
    $writer = New-Object -TypeName Windows.Storage.Streams.DataWriter -ArgumentList $stream
    $bitmap = $null
    try {
     $writer.WriteBytes([Convert]::FromBase64String($frame))
     $null = Await ($writer.StoreAsync()) ([uint32])
     $null = $writer.DetachStream()
     $stream.Seek(0)
     $decoder = Await ([Windows.Graphics.Imaging.BitmapDecoder]::CreateAsync($stream)) ([Windows.Graphics.Imaging.BitmapDecoder])
     $bitmap = Await ($decoder.GetSoftwareBitmapAsync()) ([Windows.Graphics.Imaging.SoftwareBitmap])
     $result = Await ($engine.RecognizeAsync($bitmap)) ([Windows.Media.Ocr.OcrResult])
     $texts += (($result.Lines | ForEach-Object {$_.Text}) -join "`n")
    } finally {
     if ($null -ne $bitmap) { $bitmap.Dispose() }
     $writer.Dispose(); $stream.Dispose()
    }
   }
   [Console]::WriteLine((@{id=$request.id; texts=$texts; indices=$indices; shapes=$batch.Shapes; age_ms=$captureTimer.Elapsed.TotalMilliseconds} | ConvertTo-Json -Depth 5 -Compress))
  } catch { [Console]::WriteLine((@{id=$request.id; error=$_.Exception.Message} | ConvertTo-Json -Compress)) }
 }
} catch { [Console]::WriteLine((@{ready=$false; error=$_.Exception.Message} | ConvertTo-Json -Compress)) }
'''


class CoordinateOCR:
    def __init__(self):
        self.process = None
        self.responses = queue.Queue()
        self.serial = 0
        self.lock = threading.Lock()
        self.last_texts = []
        self.preferred = None
        self.region = None
        self.capture_stamp = 0.0
        self.glyphs = GlyphReader()
        self.native_available = True

    @staticmethod
    def parse_frame(text):
        point = parse_coordinates(text)
        if point is not None:
            return point
        candidates = []
        for line in text.splitlines():
            candidate = parse_coordinates(line)
            if candidate is not None:
                candidates.append(candidate)
            elif re.search(r'\d', line):
                return None  # Do not select a pair out of extra numeric output.
        unique = set(candidates)
        return unique.pop() if len(unique) == 1 else None

    @staticmethod
    def shape_allows(text, shapes):
        digits = [char for char in text if char.isdigit()]
        comparable = [shape for shape in shapes if len(shape) == len(digits)]
        if len(comparable) < 2:
            return True
        for index, digit in enumerate(digits):
            holes = [shape[index] for shape in comparable]
            if (digit == '6' and all(count == 2 for count in holes)
                    or digit == '8' and all(count == 1 for count in holes)):
                return False
        return True

    def _receive(self, process, responses):
        try:
            for line in process.stdout:
                try:
                    responses.put_nowait(json.loads(line))
                except (ValueError, queue.Full):
                    continue
        finally:
            try:
                responses.put_nowait({'error': 'OCR işlemi kapandı'})
            except queue.Full:
                pass

    def start(self):
        if os.name != 'nt':
            raise RuntimeError('Konum okuma Windows gerektirir')
        if self.process is not None and self.process.poll() is None:
            return
        self.close()
        self.responses = queue.Queue(maxsize=4)
        # Keep Windows' command line below 32K even as the helper grows.
        payload = base64.b64encode(gzip.compress(SCRIPT.encode('utf-8'))).decode('ascii')
        bootstrap = ("$m=[IO.MemoryStream]::new([Convert]::FromBase64String('"+payload+"'));"
                     "$z=[IO.Compression.GZipStream]::new($m,[IO.Compression.CompressionMode]::Decompress);"
                     "$r=[IO.StreamReader]::new($z,[Text.Encoding]::UTF8);"
                     "$s=$r.ReadToEnd();$r.Dispose();$m.Dispose();Invoke-Expression $s")
        command = base64.b64encode(bootstrap.encode('utf-16-le')).decode('ascii')
        self.process = subprocess.Popen(
            ['powershell.exe', '-NoProfile', '-NonInteractive', '-WindowStyle', 'Hidden',
             '-EncodedCommand', command], stdin=subprocess.PIPE, stdout=subprocess.PIPE,
            stderr=subprocess.DEVNULL, text=True, encoding='utf-8', bufsize=1,
            creationflags=getattr(subprocess, 'CREATE_NO_WINDOW', 0),
        )
        threading.Thread(target=self._receive, args=(self.process, self.responses),
                         name='coordinate-ocr-output', daemon=True).start()
        try:
            response = self.responses.get(timeout=30)
            if not response.get('ready'):
                raise RuntimeError(response.get('error', 'Windows OCR başlatılamadı'))
            self.native_available = bool(response.get('ocr_available', True))
        except queue.Empty as error:
            self.close()
            raise RuntimeError('Windows OCR startup timed out') from error
        except Exception:
            self.close()
            raise

    def read(self, region, image=None):
        with self.lock:
            self.start()
            if tuple(region) != self.region:
                self.region = tuple(region)
                self.preferred = None
            self.serial += 1
            request = {'id': self.serial, 'region': region, 'image': image, 'mode': 'capture'}
            try:
                self.process.stdin.write(json.dumps(request)+'\n')
                self.process.stdin.flush()
                response = self.responses.get(timeout=6)
                if response.get('id') != self.serial or 'error' in response:
                    raise RuntimeError(response.get('error', 'Geçersiz OCR yanıtı'))
                self.capture_stamp = time.monotonic()-float(response.get('age_ms', 0))/1000
                pixels = base64.b64decode(response['pixels'])
                numeric = self.glyphs.read(pixels, region[2], region[3])
                if numeric is not None:
                    self.last_texts = [f'Rakam tanıyıcı: {numeric[0]:.1f} / {numeric[1]:.1f}']
                    return numeric
                if not self.native_available:
                    self.last_texts = ['Rakam şekli belirsiz; Windows OCR yedeği için dil bileşeni bulunamadı.']
                    return None
                capture_id = self.serial
                self.serial += 1
                fallback = {'id': self.serial, 'capture_id': capture_id, 'mode': 'ocr',
                            'region': region, 'preferred': self.preferred}
                self.process.stdin.write(json.dumps(fallback)+'\n')
                self.process.stdin.flush()
                response = self.responses.get(timeout=6)
                if response.get('id') != self.serial or 'error' in response:
                    raise RuntimeError(response.get('error', 'Geçersiz OCR yanıtı'))
                self.last_texts = response.get('texts', [])
                self.capture_stamp = time.monotonic()-float(response.get('age_ms', 0))/1000
                points = [self.parse_frame(text) if self.shape_allows(text, response.get('shapes', []))
                          else None for text in self.last_texts]
                points = [point if point is None or self.glyphs.supports_native(point) else None for point in points]
                indexed = dict(zip(response['indices'], points))
                primary = indexed.get(1)
                if primary is not None:
                    # The near-white mask excludes more background than relaxed
                    # masks. Do not let several correlated noisy masks outvote it.
                    original = indexed.get(0)
                    if original is not None and original != primary:
                        self.preferred = None
                        return None
                    self.preferred = [0, 1]
                    return primary
                valid = [point for point in points if point is not None]
                # Incomplete frames are not contradictory measurements. Every
                # complete parse must agree; temporal validation remains in the
                # controller before a center is saved or movement can start.
                if not valid:
                    self.preferred = None
                    return None
                winner = max(set(valid), key=valid.count)
                votes = valid.count(winner)
                if votes == len(valid):
                    fallback = [index for index, point in indexed.items() if point == winner][:2]
                    self.preferred = list(dict.fromkeys([0, 1, *fallback]))
                    return winner
                self.preferred = None
                return None
            except queue.Empty as error:
                self.close()
                raise RuntimeError('Windows OCR response timed out') from error
            except Exception:
                self.close()
                raise

    def close(self):
        process, self.process = self.process, None
        if process is not None:
            if process.poll() is None:
                process.terminate()
            try:
                process.wait(timeout=1)
            except subprocess.TimeoutExpired:
                process.kill()
                process.wait(timeout=1)
            for stream in (process.stdin, process.stdout):
                if stream is not None:
                    stream.close()
