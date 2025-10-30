import socket
import time
import struct
import numpy as np
import os
import sys
sys.path.append(os.path.join(os.path.dirname(__file__), 'src')) # Add src/ to path
from src.rx_control_v3 import calc_f

os.umask(0o000) #no default restriction for files

mlms=5113
bias=5101
mirr=5102
qube=5103
zf=5104
cal=5105
cal3=5120
cal4=5121
lo_mirror=5122
cryofilter=5124
sunfilter=5125
allenbradley=5123
cryo=5106
rot=5107
bat=5108
ffts=5109
ffts2=16210
hot=210 #°,mirror pos
cold=180 #°, mirror pos
on='on'
off='off'
N2=1 #valve
He=0 #valve
lo_mirror_default=189.2
lo_mirror_default_vdi=184.2
lo_mirror_default_qcl=285.0
lo_filter_default_vdi=58
lo_filter_default_qcl=111
MAIN=0b00000001 #0 (Anschluss)
CRYO=0b00000010 #1 PT Controller
USB= 0b00000100 #2
ROT= 0b00001000 #3 ->Rotator, IF-Amp, Signal-Mirror
QCL= 0b00010000 #4
VDI= 0b00100000 #5 ->2 THZ VDI Quelle
V24= 0b01000000 #6 ->24V Cal-Load, LO-Mirror,Cryofilter
VDIH=0b10000000 #7 VDI Heater
ALL= 0b01111111
MIN=MAIN+CRYO
INI=MIN+USB+V24

#s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
#s.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
#s.settimeout(5)

#socketType=socket.SOCK_STREAM #TCP
SOCKET_TYPE={'UDP':socket.SOCK_DGRAM,'TCP':socket.SOCK_STREAM}
TIMEOUT = 10
#IP_BALLOON_PI='172.16.18.110'
#IP_SUPPLY_PI='172.16.18.111'
IP_BALLOON_PI='172.20.4.130'
IP_SUPPLY_PI='172.20.4.131'

ports={}
k=None
for k in locals():
    try:
        if locals()[k] > 5100: ports.update({locals()[k]:k})
    except:
        pass
    
contextmanager=None

def print2cm(*args):
    if contextmanager==None:print(*args)
    else:
        with contextmanager:
            print(*args)
        
def cmd(port, command,ip=IP_BALLOON_PI,verbose=0, noansw=0, answerTerminated=True, packetlen=1024,timeout=TIMEOUT,socketType='UDP'):
   try: pname=ports[port]
   except: pname=''
   if verbose:print2cm(f'{ip},{socketType} {port}({pname}):', command) 
   with socket.socket(socket.AF_INET, SOCKET_TYPE[socketType]) as s:
      s.connect((ip, port))
      s.settimeout(timeout)
      s.send(command)
      if noansw:
            if verbose: print2cm('no answer expected')
            return
      answ=b''
      try:
          #print(packetlen)
          answ = s.recv(packetlen)
         # print(answ)
          if answerTerminated == True:
              while answ[-1]!=10: answ=answ+s.recv(packetlen)
          elif packetlen!=1024:
              while len(answ)<packetlen: answ=answ+s.recv(packetlen-len(answ))       
      except socket.timeout:
          print2cm(f'socket timeout,received:{answ}')
          s.shutdown(socket.SHUT_RDWR) #to close port
          #s.recv(0)
      if verbose: print2cm('<-:',answ)
      return(answ)
    
def cmdv(*args,**kwargs): return cmd(*args,**kwargs,verbose = 1)
def cmds(*args,**kwargs): return cmd(*args,**kwargs,ip = IP_SUPPLY_PI)

def initcryo(valvepos=0):
   cmd(cryo,b'EDRM 1\n',verbose=1) #init pressure sensors
   cmd(cryo,f'ENPV {valvepos} {valvepos}\n'.encode(),verbose=1) #init valves

def initoptics():
   cmd(cal,b'SETTEMP 125\n',verbose=1)
   cmd(mirr,b'HOME\n',verbose=1)
   cmd(mirr,b'SET OFFSET -143.8\n',verbose=1)
   cmd(mirr,b'GO 0\n',verbose=1)
   rotheat(off)
#   cmd(cal3,b'SETTEMP -70\n',verbose=1)
#   cmd(cal3,b'SETPARAM 2030 4.0\n',verbose=1) #max current
#   cmd(cal3,b'SETPARAM 2031 12.0\n',verbose=1) #max voltage
   cmd(lo_mirror,f'HOME\n'.encode(),verbose=1)

def heatN2(onoff, Tmax=310):
   if onoff==on:
      cr(f'SHUL 1 {Tmax}')
      cr('ENHE 1 1')
   else:
      cr('ENHE 1 0')

def heatHe(onoff, Tmax=310):
   if onoff==on:
      cr(f'SHUL 0 {Tmax}')
      cr('ENHE 0 1')
   else:
      cr('ENHE 0 0')
        
def spos(valve,pos): return cmd(cryo,f'SPOS {valve} {pos}\n'.encode(),verbose=1)
      
def cr(command):return cmd(cryo,command.encode()+b'\n',verbose=1)
       
def iset(mA): 
    if mA: return cmd(qube,f'iset:{mA}\n'.encode(),noansw=1,verbose=1)

def iout(onoff): 
    if onoff: return cmd(qube,f'iout:{onoff}\n'.encode(),noansw=1,verbose=1)

def tlim(): return cmd(qube,b'teslim:1000\n',noansw=True,verbose=1)

def tstab(onoff): 
    if onoff: return cmd(qube,f'tstab:{onoff}\n'.encode(),noansw=1,verbose=1)

def tset(T): 
    if T: return cmd(qube,f'tset:{T}\n'.encode(),noansw=1,verbose=1)

def go(pos,device=mirr): #0->180: Spiegel dreht sich untenrum, 0->-180: obenrum
    return cmd(device,f'GO {pos}\n'.encode(),verbose=1)

def golo(pos): go(pos,lo_mirror)

def gofilter(pos):
    cmd(cryofilter,b'SWITCH ON\n')
    go(pos,cryofilter)
    cmd(cryofilter,b'SWITCH OFF\n')

def initfilter(moveto=-3):
    gofilter(110)
    gofilter(0)
    for i in range(0,5):
        cmd(cryofilter,b'HOME\n',verbose=1)
        gofilter(moveto)
#        cmd(cryofilter,b'SWITCH OFF\n',verbose=1)
    

def att_(dB):
   if dB == 0: cmd(zf,b'gjihkl')
   elif dB == 4: cmd(zf,b'gJihkl')
   elif dB == 8: cmd(zf,b'gjihKl')
   elif dB == 12: cmd(zf,b'gJihKl')

def att(dB):
   s=b''
   if (dB-16) >= 0 : s=s+b'L';dB=dB-16
   else: s=s+b'l'
   if (dB-8) >=0: s=s+b'K';dB=dB-8
   else: s=s+b'k'
   if (dB-4)>=0: s=s+b'J';dB=dB-4
   else: s=s+b'j'
   if (dB-2)>=0: s=s+b'I';dB=dB-2
   else: s=s+b'i'
   if (dB-1)>=0: s=s+b'H';dB=dB-1
   else: s=s+b'h'
   if (dB-0.5)>=0:s=s+b'G';dB=dB-0.5
   else:s=s+b'g'
   return cmd(zf,s)

def ifband(band):
    if band==1:return cmd(zf,b'1')
    if band==2:return cmd(zf,b'2')

def power(ch):
   k=b'SETA'+ch.to_bytes(1,'big')+b'\n'
   #print(k)
   return cmds(5110,k,verbose=1)

def heatwindow(onoff):
    if onoff == 'on':
       return cmds(5110,b'SETB\x01\n')
    elif onoff == 'off':
       return cmds(5110,b'SETB\x00\n')

def heatbiasbox(onoff):
    if onoff == 'on':
       return cmds(5110,b'SETB\x02\n')
    elif onoff == 'off':
       return cmds(5110,b'SETB\x00\n')

def rebootsupply(): return cmd(ffts,b'REBOOT SUPPLY\n')

def rebootpi(): return cmds(5110,b'REBOOT\n')
   
def dumpffts(): 
   cmd(ffts2,b'AFFTS:STOP \n')
   cmd(ffts2,b'AFFTS:CMDMODE INTERNAL \n')
   cmd(ffts2,b'AFFTS:cmdSyncTime 1000000 \n')
   cmd(ffts2,b'AFFTS:CMDUSEDSECTIONS 1 \n')
   cmd(ffts2,b'AFFTS:CONFIGURE \n')
   cmd(ffts2,b'AFFTS:START \n')
   time.sleep(1)
#   cmd(ffts2,b'AFFTS:DUMP\n')
   cmd(ffts2,b'AFFTS:STOP \n')
    
def pidHe(pressure = 1020,I=0.1, P=50,ggw=370):
   cr('MODE 0 1') #Druckregelung
   cr('ENPI 0 1') #Regler an
   cr(f'SRFP 0 {pressure}') #Setpoint
   cr('SETD 0 0') 
   cr(f'SETI 0 {I}')
   cr(f'SETP 0 {P}')
   cr('SETL 0 100000') #fehlerlimit
   cr('SRSM 0 100') #maximale schrittweite
   cr(f'SVOF 0 {ggw}')# Gleichgewichtsposition
   cr('SRVM 0 900') #maximale Ventilöffnung

def pidN2(pressure = 1020, I=1, P=50, ggw=800, maxV=3000):
   cr('MODE 1 1') #Druckregelung
   cr('ENPI 1 1') #Regler an
   cr(f'SRFP 1 {pressure}') #Setpoint
   cr('SETD 1 0') 
   cr(f'SETI 1 {I}')
   cr(f'SETP 1 {P}')
   cr('SETL 1 10000') #fehlerlimit
   cr('SRSM 1 100') #maximale schrittweite
   cr(f'SVOF 1 {ggw}')# Gleichgewichtsposition
   cr(f'SRVM 1 {maxV}') #maximale Ventilöffnung

def pidN2_T(temp):
   cr('MODE 1 0') #Druckregelung
   cr('ENPI 1 1') #Regler an
   cr(f'SRFT 1 {temp}') #Setpoint
   cr('SETD 1 0') 
   cr('SETI 1 1')
   cr('SETP 1 50')
   cr('SETL 1 10000') #fehlerlimit
   cr('SRSM 1 100') #maximale schrittweite
   cr('SVOF 1 800')# Gleichgewichtsposition
   cr('SRVM 1 3000') #maximale Ventilöffnung
    
def fftsc(onoff):
   if onoff == on:
      cmd(ffts,b'SWITCH ON',verbose=1)
      time.sleep(1)
      cmd(ffts,b'BOOT',verbose=1)
   if onoff == off:
      cmd(ffts,b'STOP',verbose=1)
      time.sleep(1)
      cmd(ffts,b'SWITCH OFF',verbose=1)

def affts(command): print2cm(cmd(ffts2,command.encode()+b' \n',answerTerminated=False))

def calffts(): 
   answ=cmd(ffts2,b'AFFTS:STOP\n')
   answ=answ+cmd(ffts2,b'AFFTS:CALFFTS\n')
   return(answ)

def configaffts(intTime=1e6): #integration time, us
    affts('AFFTS:STOP')
    affts('AFFTS:CMDMODE INTERNAL')
    affts(f'AFFTS:cmdSyncTime {round(intTime):d}')
    affts('AFFTS:CMDUSEDSECTIONS 1')
    affts('AFFTS:CMDNUMPHASES 1')
    affts('AFFTS:CONFIGURE')
    
def measure(pos=0,ndumps=1,timePerDump=0.25,socketType='UDP',nbins=4096):
    go(pos)
    answ=cmd(5112,f'DUMP {ndumps}'.encode(),timeout=timePerDump*ndumps*2,socketType=socketType)
    print2cm(answ)
    with open('/ramdisk/dumplog.hk','a') as f: f.write(answ.decode())
    fn=answ.decode().split()[2]
    tstamp=answ.decode().split()[0]
    bindata=cmd(5112,f'GET {fn}'.encode(),answerTerminated=False,packetlen=nbins*4,timeout=5,socketType=socketType)
   # print(len(bindata))
    spec=np.asarray(struct.unpack(f'{nbins}f',bindata))
    specdir='/ramdisk/spec'
    if (not os.path.isdir(specdir)): os.mkdir(specdir)
    with open(f'{specdir}/{tstamp}.spec','wb') as f: f.write(bindata)
    return spec,answ

def rotstep(step=1): return cmd(rot,f'JOGSTEP {step}'.encode())

def rotgo(pos): return cmd(rot,f'GOTO {pos}'.encode())
    
def rotfw(): return cmd(rot,b'FW')
    
def rotbw(): return cmd(rot,b'BW')
    
def rotgetpos(): return float(cmd(rot,b'GET'))

def rotheat(onoff):
   if onoff==on:
      return cmd(cal,b'ROTHEATER ON',verbose=1)
   elif onoff==off:
      return cmd(cal,b'ROTHEATER OFF',verbose=1)


def sweep(type=1):
    scmd = b'S'
    if type == 2: scmd=b's'
    answ=cmd(bias,scmd,answerTerminated = False,packetlen = 518)
    if (answ[0:1] != b'#') | (answ[517:] != b'!'): raise ValueError('HEB sweep data stream error.')  
    data=np.array(list(struct.iter_unpack('>HH',answ[1:-1])),dtype=np.float64)
    data=data*0.000152737-1.25
    I=data[:,0]/3640*1e6 #in uA
    V=data[:,1]/75.5*1e3 #in mV
  #  I=data[:,0]
  #  V=data[:,1]
    return V,I

def slowsweep(npoints=5):
    cmd(bias,b'DISABLE HK',noansw=1)
  #  cmd(bias,b'rud') #to make sure to be at real zero
    cmd(bias,b'r')
    time.sleep(0.25)

    clist='u'*2*npoints+'U'*npoints+'G'*npoints+'H'*npoints+'D'*npoints+'d'*4*npoints+'D'*npoints+'H'*npoints+'G'*npoints+'U'*npoints+'u'*2*npoints
    V,I=np.zeros(len(clist)),np.zeros(len(clist))
    for i in range(0,len(clist)):    
        r=cmd(bias,b'z').decode().split()
        V[i],I[i]=float(r[0]),float(r[1])
        c=clist[i]
        if c=='G':cmd(bias,b'UUUUU')
        elif c=='H':cmd(bias,b'DDDDD')
        else: cmd(bias,c.encode())
        time.sleep(0.25)
  #  I=data[:,0]
  #  V=data[:,1]
    cmd(bias,b'ENABLE HK',noansw=1)
    return V,I

def fftsguidata(socketType='UDP'):
    answ=cmd(ffts2,b'AFFTS:BAND1:GUIINFO \n',answerTerminated=False)
    nbytes=int(str.split(answ.decode())[2]) #always 33792
    buf=cmd(ffts2,b'AFFTS:BAND1:GUIDATA \n',answerTerminated=False,packetlen=nbytes,socketType=socketType,timeout=2)
    ndata=nbytes-1024
    #    data=buf[-32768:]
    data=buf[-ndata:]
    nfloats=ndata//4
    spec=np.asarray(struct.unpack(f'>{nfloats}f',data))
    adclev=np.asarray(struct.unpack('>64L',buf[512:(512+256)]))[::2];
    return spec,adclev,buf

def restart(service='TCP2UDP'): #USB|UDP|devicelevel|TCP2UDP|all
    sshcmd=f'sshpass -f /osasb/.rsync_pass ssh pi@172.16.18.110 /home/pi/restart.sh {service}'
    os.system(sshcmd)

def fvdi(freq): return cmd(mlms,f'F{freq:.6f}'.encode())
