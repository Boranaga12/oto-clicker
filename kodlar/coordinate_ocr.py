"""A single persistent Windows OCR process; no cloud or Python dependencies."""
from __future__ import annotations

import base64
import json
import os
import queue
import subprocess
import threading

from .position_model import parse_coordinates


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
 if ($null -eq $engine) { throw 'Windows OCR language is not installed' }
 Add-Type -ReferencedAssemblies System.Drawing -TypeDefinition @'
using System;
using System.Drawing;
using System.Drawing.Imaging;
using System.Drawing.Drawing2D;
using System.IO;
using System.Runtime.InteropServices;
using System.Collections.Generic;
public static class CoordinateFrames {
 [DllImport("user32.dll")] static extern bool SetProcessDpiAwarenessContext(IntPtr context);
 static CoordinateFrames() {
  try { SetProcessDpiAwarenessContext(new IntPtr(-4)); } catch(EntryPointNotFoundException) { }
 }
 public static string[] Make(int x, int y, int w, int h, string image) {
  using (Bitmap source = new Bitmap(w,h,PixelFormat.Format32bppArgb)) {
   using (Graphics g = Graphics.FromImage(source)) {
    if (String.IsNullOrEmpty(image)) g.CopyFromScreen(x,y,0,0,new Size(w,h),CopyPixelOperation.SourceCopy);
    else using (MemoryStream stream = new MemoryStream(Convert.FromBase64String(image)))
     using (Bitmap input = new Bitmap(stream)) g.DrawImage(input,new Rectangle(0,0,w,h),new Rectangle(x,y,w,h),GraphicsUnit.Pixel);
   }
   List<string> frames = new List<string>();
   frames.Add(Encode(source, false, 4, false));
   frames.Add(Encode(source, false, 4, true));
   frames.Add(Encode(source, false, 8, true));
   using(Bitmap inverted = new Bitmap(w,h,PixelFormat.Format32bppArgb)) {
    for(int py=0;py<h;py++) for(int px=0;px<w;px++) {
     Color pixel=source.GetPixel(px,py);
     int grey=(pixel.R*299+pixel.G*587+pixel.B*114)/1000;
     inverted.SetPixel(px,py,Color.FromArgb(255-grey,255-grey,255-grey));
    }
    frames.Add(Encode(inverted, true, 4, true));
    frames.Add(Encode(inverted, true, 6, true));
    frames.Add(Encode(inverted, true, 4, true, 6));
    frames.Add(Encode(inverted, true, 4, true, 8));
   }
   foreach(int threshold in new int[]{125,145,165,185})
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
    frames.Add(Encode(mask, true, 4, true));
    frames.Add(Encode(mask, true, 4, false));
    frames.Add(Encode(mask, true, 6, true));
    frames.Add(Encode(mask, true, 8, false));
    frames.Add(Encode(mask, true, 4, true, 6));
    frames.Add(Encode(mask, true, 4, true, 8));
    using(Bitmap pair=Separate(mask, false)) {
     if(pair!=null) frames.Add(Encode(pair, true, 4, true));
    }
    using(Bitmap pair=Separate(mask, true)) {
     if(pair!=null) frames.Add(Encode(pair, true, 4, true));
    }
   }
   return frames.ToArray();
  }
 }
 static Bitmap Separate(Bitmap source, bool stacked) {
  int best=0, split=0, run=0;
  for(int x=source.Width/4;x<source.Width*3/4;x++) {
   bool blank=true;
   for(int y=0;y<source.Height;y++) if(source.GetPixel(x,y).R<128) {blank=false;break;}
   run=blank ? run+1 : 0;
   if(run>best) {best=run;split=x-run/2;}
  }
  if(best<2) return null;
  Bitmap result=new Bitmap(stacked ? Math.Max(split,source.Width-split) : source.Width+24,
                            stacked ? source.Height*2+12 : source.Height);
  using(Graphics g=Graphics.FromImage(result)) {
   g.Clear(Color.White);
   g.DrawImage(source,new Rectangle(0,0,split,source.Height),new Rectangle(0,0,split,source.Height),GraphicsUnit.Pixel);
   g.DrawImage(source,new Rectangle(stacked?0:split+24,stacked?source.Height+12:0,source.Width-split,source.Height),
               new Rectangle(split,0,source.Width-split,source.Height),GraphicsUnit.Pixel);
  }
  return result;
 }
 static string Encode(Bitmap source, bool mask, int scale, bool smooth, int vertical=0) {
  if(vertical==0) vertical=scale;
  using(Bitmap scaled=new Bitmap(source.Width*scale+32,source.Height*vertical+32,PixelFormat.Format32bppArgb)) {
   using(Graphics g=Graphics.FromImage(scaled)) {
    g.Clear(mask ? Color.White : Color.Black);
    g.InterpolationMode=smooth ? InterpolationMode.HighQualityBicubic : InterpolationMode.NearestNeighbor;
    g.PixelOffsetMode=PixelOffsetMode.Half;
    g.DrawImage(source,new Rectangle(16,16,source.Width*scale,source.Height*vertical));
   }
   using(MemoryStream stream=new MemoryStream()) {
    scaled.Save(stream,ImageFormat.Png); return Convert.ToBase64String(stream.ToArray());
   }
  }
 }
}
'@
 [Console]::WriteLine('{"ready":true}')
 while ($null -ne ($line = [Console]::ReadLine())) {
  try {
   $request = $line | ConvertFrom-Json
   $r = $request.region
   if ($r.Count -ne 4 -or $r[2] -lt 8 -or $r[2] -gt 640 -or $r[3] -lt 8 -or $r[3] -gt 180) { throw 'Invalid coordinate region' }
   $frames = [CoordinateFrames]::Make($r[0],$r[1],$r[2],$r[3],$request.image)
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
   [Console]::WriteLine((@{id=$request.id; texts=$texts; indices=$indices} | ConvertTo-Json -Compress))
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
        command = base64.b64encode(SCRIPT.encode('utf-16-le')).decode('ascii')
        self.process = subprocess.Popen(
            ['powershell.exe', '-NoProfile', '-NonInteractive', '-WindowStyle', 'Hidden',
             '-EncodedCommand', command], stdin=subprocess.PIPE, stdout=subprocess.PIPE,
            stderr=subprocess.DEVNULL, text=True, encoding='utf-8', bufsize=1,
            creationflags=getattr(subprocess, 'CREATE_NO_WINDOW', 0),
        )
        threading.Thread(target=self._receive, args=(self.process, self.responses),
                         name='coordinate-ocr-output', daemon=True).start()
        try:
            response = self.responses.get(timeout=15)
            if not response.get('ready'):
                raise RuntimeError(response.get('error', 'Windows OCR başlatılamadı'))
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
            request = {'id': self.serial, 'region': region, 'image': image,
                       'preferred': self.preferred}
            try:
                self.process.stdin.write(json.dumps(request)+'\n')
                self.process.stdin.flush()
                response = self.responses.get(timeout=6)
                if response.get('id') != self.serial or 'error' in response:
                    raise RuntimeError(response.get('error', 'Geçersiz OCR yanıtı'))
                self.last_texts = response.get('texts', [])
                points = [parse_coordinates(text) for text in self.last_texts]
                valid = [point for point in points if point is not None]
                # A single plausible OCR result is not sufficient for movement.
                # Independently prepared frames must agree on both decimals.
                if not valid:
                    self.preferred = None
                    return None
                winner = max(set(valid), key=valid.count)
                votes = valid.count(winner)
                if votes >= 2 and votes/len(valid) >= 2/3:
                    self.preferred = [index for index, point in zip(response['indices'], points)
                                      if point == winner][:2]
                    return winner
                self.preferred = None
                return None
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
