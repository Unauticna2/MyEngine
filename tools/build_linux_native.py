"""Build the same MASM physics for Linux ELF64, plus the C++ 4D kernel."""
from pathlib import Path
import argparse,subprocess,re,shutil,platform

def build(root,jwasm='jwasm'):
    root=Path(root).resolve()
    if platform.system()!='Linux' or platform.machine() not in ('x86_64','AMD64'):raise RuntimeError('Build this backend on Linux x86_64')
    if not shutil.which(str(jwasm)):raise RuntimeError('Install JWasm (Masm-compatible assembler), or pass --jwasm /path/to/jwasm')
    target=root/'platforms/linux';target.mkdir(parents=True,exist_ok=True);temp=root/'build/linux';temp.mkdir(parents=True,exist_ok=True)
    text=(root/'Physics.asm').read_text().replace('PROC FRAME','PROC')
    text=re.sub(r'^\s*\.(?:pushreg|allocstack|endprolog|savereg|savexmm128)\b.*$', '',text,flags=re.M|re.I)
    source=temp/'Physics_linux.asm';source.write_text(text)
    subprocess.run([str(jwasm),'-elf64',f'-Fo={temp/"Physics.o"}',str(source)],check=True)
    subprocess.run(['gcc','-shared','-fPIC','-O2','-Wl,-z,noexecstack','-o',str(target/'libMyEnginePhysics.so'),str(temp/'Physics.o'),str(target/'physics_abi.c')],check=True)
    subprocess.run(['g++','-std=c++17','-O3','-shared','-fPIC','-pthread',str(root/'Slice4D.cpp'),'-o',str(target/'libSlice4D.so')],check=True)
    subprocess.run(['g++','-std=c++17','-O3','-shared','-fPIC',str(root/'MyEngineUI.cpp'),'-o',str(target/'libMyEngineUI.so')],check=True)
    subprocess.run(['g++','-std=c++17','-O3','-shared','-fPIC',str(root/'FluidNative.cpp'),'-o',str(target/'libFluidNative.so')],check=True)
    return target
if __name__=='__main__':
    p=argparse.ArgumentParser();p.add_argument('--jwasm',default='jwasm');args=p.parse_args();print(build(Path(__file__).resolve().parents[1],args.jwasm))
