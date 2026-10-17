; Camera entity + movement system. Worker is the sole owner of camera state.
; UI only publishes naturally aligned integer inputs. MASM x64 / Win64 ABI.
option casemap:none
PUBLIC UpdateCamera, cameraPosition, cameraPitch, cameraYaw
PUBLIC controlBits, mouseDX, mouseDY, resetRequest
PUBLIC EngineGetCameraControl, EngineGetRuntimeFlags, runtimeFlags
.data
ALIGN 4
runtimeFlags DWORD 15
cameraControlEnabled DWORD 1
controlBits DWORD 0
mouseDX DWORD 0
mouseDY DWORD 0
resetRequest DWORD 0
cameraPosition REAL4 0.0,2.0,7.0
cameraPitch REAL4 12.0
cameraYaw REAL4 0.0
cameraW REAL4 0.0
fMouseSpeed REAL4 0.18
fLookSpeed REAL4 90.0
fMoveSpeed REAL4 4.0
fFastSpeed REAL4 12.0
fTurn REAL4 360.0
fMinPitch REAL4 -89.0
fMaxPitch REAL4 89.0
fOne REAL4 1.0
fRadians REAL4 0.017453292519943295

.code
EngineGetRuntimeFlags PROC
    lea rax,runtimeFlags
    ret
EngineGetRuntimeFlags ENDP
EngineGetCameraControl PROC
    lea rax,cameraControlEnabled
    ret
EngineGetCameraControl ENDP
; Bits: W=1 S=2 A=4 D=8 Space=16 Ctrl=32 Shift=64
; Left=128 Right=256 Up=512 Down=1024. XMM0=delta seconds.
UpdateCamera PROC FRAME
    sub rsp,38h
    .allocstack 38h
    .endprolog
    movss REAL4 PTR [rsp+20h],xmm0
    mov r10d,controlBits             ; one consistent key snapshot per update
    test runtimeFlags,1
    jnz cam_look_enabled
    xor eax,eax
    xchg eax,mouseDX
    xor eax,eax
    xchg eax,mouseDY
    jmp cam_movement
cam_look_enabled:
    xor eax,eax
    xchg eax,mouseDX
    cvtsi2ss xmm1,eax
    mulss xmm1,fMouseSpeed
    addss xmm1,cameraYaw
    xor eax,eax
    xchg eax,mouseDY
    cvtsi2ss xmm2,eax
    mulss xmm2,fMouseSpeed
    addss xmm2,cameraPitch
    mulss xmm0,fLookSpeed
    test r10d,128
    jz cam_right
    subss xmm1,xmm0
cam_right:
    test r10d,256
    jz cam_up
    addss xmm1,xmm0
cam_up:
    test r10d,512
    jz cam_down
    subss xmm2,xmm0
cam_down:
    test r10d,1024
    jz cam_angles
    addss xmm2,xmm0
cam_angles:
    maxss xmm2,fMinPitch
    minss xmm2,fMaxPitch
    movss cameraPitch,xmm2
    movaps xmm3,xmm1
    divss xmm3,fTurn
    cvttss2si eax,xmm3
    cvtsi2ss xmm3,eax
    mulss xmm3,fTurn
    subss xmm1,xmm3
    movss cameraYaw,xmm1
cam_movement:
    movss xmm1,cameraYaw
    test runtimeFlags,8
    jz cam_translation_done
    cmp cameraControlEnabled,0
    je cam_translation_done
    mulss xmm1,fRadians
    movss REAL4 PTR [rsp],xmm1
    fld REAL4 PTR [rsp]
    fsincos                         ; ST0=cos yaw, ST1=sin yaw
    fstp REAL4 PTR [rsp+4]
    fstp REAL4 PTR [rsp+8]
    movss xmm4,REAL4 PTR [rsp+4]
    movss xmm5,REAL4 PTR [rsp+8]
    xorps xmm0,xmm0                  ; forward/backward
    xorps xmm1,xmm1                  ; right/left
    xorps xmm2,xmm2                  ; up/down
    test r10d,1
    jz cam_back
    addss xmm0,fOne
cam_back:
    test r10d,2
    jz cam_left_move
    subss xmm0,fOne
cam_left_move:
    test r10d,4
    jz cam_right_move
    subss xmm1,fOne
cam_right_move:
    test r10d,8
    jz cam_rise
    addss xmm1,fOne
cam_rise:
    test r10d,16
    jz cam_fall
    addss xmm2,fOne
cam_fall:
    test r10d,32
    jz cam_normalize
    subss xmm2,fOne
cam_normalize:
    movaps xmm3,xmm0
    mulss xmm3,xmm3
    movss REAL4 PTR [rsp+12],xmm3
    movaps xmm3,xmm1
    mulss xmm3,xmm3
    addss xmm3,REAL4 PTR [rsp+12]
    movss REAL4 PTR [rsp+12],xmm3
    movaps xmm3,xmm2
    mulss xmm3,xmm3
    addss xmm3,REAL4 PTR [rsp+12]
    maxss xmm3,fOne                  ; zero input stays zero; diagonals normalized
    sqrtss xmm3,xmm3
    divss xmm0,xmm3
    divss xmm1,xmm3
    divss xmm2,xmm3
    movss xmm3,REAL4 PTR [rsp+20h]
    test r10d,64
    jnz cam_fast
    mulss xmm3,fMoveSpeed
    jmp cam_step
cam_fast:
    mulss xmm3,fFastSpeed
cam_step:
    mulss xmm0,xmm3
    mulss xmm1,xmm3
    mulss xmm2,xmm3
    lea r11,cameraPosition
    addss xmm2,REAL4 PTR [r11+4]
    movss REAL4 PTR [r11+4],xmm2
    movaps xmm2,xmm0
    mulss xmm2,xmm5                  ; X = forward*sin + right*cos
    movaps xmm3,xmm1
    mulss xmm3,xmm4
    addss xmm2,xmm3
    addss xmm2,REAL4 PTR [r11]
    movss REAL4 PTR [r11],xmm2
    mulss xmm1,xmm5                  ; Z = right*sin - forward*cos
    mulss xmm0,xmm4
    subss xmm1,xmm0
    addss xmm1,REAL4 PTR [r11+8]
    movss REAL4 PTR [r11+8],xmm1
cam_translation_done:
    lea r11,cameraPosition
    xor eax,eax
    xchg eax,resetRequest
    test eax,eax
    jz cam_done
    test runtimeFlags,2
    jz cam_done
    mov DWORD PTR [r11],0
    mov DWORD PTR [r11+4],40000000h   ; 2.0
    mov DWORD PTR [r11+8],40E00000h   ; 7.0
    mov cameraW,0
    mov cameraYaw,0
    mov cameraPitch,41400000h        ; 12.0
cam_done:
    add rsp,38h
    ret
UpdateCamera ENDP
END
