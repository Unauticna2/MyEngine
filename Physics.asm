; Native rigid-box / triangle-mesh physics. MASM x64, SSE2, Win64 ABI.
; All writable state is passed by the caller; no global scratch buffers.
; Body = 256 bytes, Contact = 80, Pair = 16, BVH node = 48, Triangle = 48.
option casemap:none
PUBLIC PhysicsPrepare, PhysicsIntegrate, PhysicsBoxBox, PhysicsBoxTriangle
PUBLIC PhysicsBoxContacts, PhysicsMeshContacts, PhysicsSolve

B_POS EQU 0
B_VEL EQU 16
B_FORCE EQU 32
B_QUAT EQU 48
B_OMEGA EQU 64
B_TORQUE EQU 80
B_HALF EQU 96
B_AX0 EQU 112
B_AX1 EQU 128
B_AX2 EQU 144
B_INERTIA EQU 160
B_MASS EQU 176                 ; inverse mass: zero for static/kinematic
B_GRAVITY EQU 180
B_DRAG EQU 184
B_ADRAG EQU 188
B_FRICTION EQU 192
B_BOUNCE EQU 196
B_FLAGS EQU 200                ; active=1, dynamic=2, freeze rotation=4
B_GROUND EQU 204
B_LOW EQU 208
B_HIGH EQU 224
B_PREVIOUS EQU 240

; Dot product of four floats. Vector padding must be zero (quaternion uses w).
VDOT MACRO dst, pa, pb, tmp
    movups dst,XMMWORD PTR [pa]
    mulps dst,XMMWORD PTR [pb]
    movaps tmp,dst
    shufps tmp,tmp,4Eh
    addps dst,tmp
    movaps tmp,dst
    shufps tmp,tmp,0B1h
    addss dst,tmp
ENDM
VCROSS MACRO dst, pa, pb, t1, t2
    movups dst,XMMWORD PTR [pa]
    movups t1,XMMWORD PTR [pb]
    shufps dst,dst,0C9h
    shufps t1,t1,0D2h
    mulps dst,t1
    movups t1,XMMWORD PTR [pa]
    movups t2,XMMWORD PTR [pb]
    shufps t1,t1,0D2h
    shufps t2,t2,0C9h
    mulps t1,t2
    subps dst,t1
ENDM
.const
ALIGN 16
pAbs DWORD 7FFFFFFFh,7FFFFFFFh,7FFFFFFFh,7FFFFFFFh
pSign DWORD 80000000h,80000000h,80000000h,80000000h
pOne REAL4 1.0
pTwo REAL4 2.0
pThree REAL4 3.0
pHalf REAL4 0.5
pEpsilon REAL4 0.000000000001
pContactEps REAL4 0.00001
pSlop REAL4 0.001
pCorrection REAL4 0.65
pGround REAL4 0.55
pBounceThreshold REAL4 -1.0
pHuge REAL4 1.0e30

.code
; Recompute principal inverse inertia, quaternion axes and world AABB.
; RCX=Body[], EDX=count.
PhysicsPrepare PROC
    test edx,edx
    jz prepare_done
prepare_body:
    ; Quaternion to columns of R. q=(x,y,z,w), normalized by integration.
    movss xmm0,REAL4 PTR [rcx+B_QUAT+4]
    mulss xmm0,xmm0
    movss xmm1,REAL4 PTR [rcx+B_QUAT+8]
    mulss xmm1,xmm1
    addss xmm0,xmm1
    mulss xmm0,pTwo
    movss xmm1,pOne
    subss xmm1,xmm0
    movss REAL4 PTR [rcx+B_AX0],xmm1
    movss xmm0,REAL4 PTR [rcx+B_QUAT]
    mulss xmm0,REAL4 PTR [rcx+B_QUAT+4]
    movss xmm1,REAL4 PTR [rcx+B_QUAT+12]
    mulss xmm1,REAL4 PTR [rcx+B_QUAT+8]
    movaps xmm2,xmm0
    addss xmm0,xmm1
    subss xmm2,xmm1
    mulss xmm0,pTwo
    mulss xmm2,pTwo
    movss REAL4 PTR [rcx+B_AX0+4],xmm0
    movss REAL4 PTR [rcx+B_AX1],xmm2
    movss xmm0,REAL4 PTR [rcx+B_QUAT]
    mulss xmm0,REAL4 PTR [rcx+B_QUAT+8]
    movss xmm1,REAL4 PTR [rcx+B_QUAT+12]
    mulss xmm1,REAL4 PTR [rcx+B_QUAT+4]
    movaps xmm2,xmm0
    subss xmm0,xmm1
    addss xmm2,xmm1
    mulss xmm0,pTwo
    mulss xmm2,pTwo
    movss REAL4 PTR [rcx+B_AX0+8],xmm0
    movss REAL4 PTR [rcx+B_AX2],xmm2
    movss xmm0,REAL4 PTR [rcx+B_QUAT]
    mulss xmm0,xmm0
    movss xmm1,REAL4 PTR [rcx+B_QUAT+8]
    mulss xmm1,xmm1
    addss xmm0,xmm1
    mulss xmm0,pTwo
    movss xmm1,pOne
    subss xmm1,xmm0
    movss REAL4 PTR [rcx+B_AX1+4],xmm1
    movss xmm0,REAL4 PTR [rcx+B_QUAT+4]
    mulss xmm0,REAL4 PTR [rcx+B_QUAT+8]
    movss xmm1,REAL4 PTR [rcx+B_QUAT+12]
    mulss xmm1,REAL4 PTR [rcx+B_QUAT]
    movaps xmm2,xmm0
    addss xmm0,xmm1
    subss xmm2,xmm1
    mulss xmm0,pTwo
    mulss xmm2,pTwo
    movss REAL4 PTR [rcx+B_AX1+8],xmm0
    movss REAL4 PTR [rcx+B_AX2+4],xmm2
    movss xmm0,REAL4 PTR [rcx+B_QUAT]
    mulss xmm0,xmm0
    movss xmm1,REAL4 PTR [rcx+B_QUAT+4]
    mulss xmm1,xmm1
    addss xmm0,xmm1
    mulss xmm0,pTwo
    movss xmm1,pOne
    subss xmm1,xmm0
    movss REAL4 PTR [rcx+B_AX2+8],xmm1
    mov DWORD PTR [rcx+B_AX0+12],0
    mov DWORD PTR [rcx+B_AX1+12],0
    mov DWORD PTR [rcx+B_AX2+12],0
    mov DWORD PTR [rcx+B_INERTIA+12],0
    movss xmm4,REAL4 PTR [rcx+B_MASS]
    mulss xmm4,pThree
    test DWORD PTR [rcx+B_FLAGS],4
    jz prepare_inertia
    xorps xmm4,xmm4
prepare_inertia:
    movss xmm0,REAL4 PTR [rcx+B_HALF]
    mulss xmm0,xmm0
    movss xmm1,REAL4 PTR [rcx+B_HALF+4]
    mulss xmm1,xmm1
    movss xmm2,REAL4 PTR [rcx+B_HALF+8]
    mulss xmm2,xmm2
    movaps xmm3,xmm1
    addss xmm3,xmm2
    maxss xmm3,pEpsilon
    movaps xmm5,xmm4
    divss xmm5,xmm3
    movss REAL4 PTR [rcx+B_INERTIA],xmm5
    movaps xmm3,xmm0
    addss xmm3,xmm2
    maxss xmm3,pEpsilon
    movaps xmm5,xmm4
    divss xmm5,xmm3
    movss REAL4 PTR [rcx+B_INERTIA+4],xmm5
    addss xmm0,xmm1
    maxss xmm0,pEpsilon
    divss xmm4,xmm0
    movss REAL4 PTR [rcx+B_INERTIA+8],xmm4
    movups xmm0,XMMWORD PTR [rcx+B_AX0]
    andps xmm0,XMMWORD PTR pAbs
    movss xmm1,REAL4 PTR [rcx+B_HALF]
    shufps xmm1,xmm1,0
    mulps xmm0,xmm1
    movups xmm2,XMMWORD PTR [rcx+B_AX1]
    andps xmm2,XMMWORD PTR pAbs
    movss xmm1,REAL4 PTR [rcx+B_HALF+4]
    shufps xmm1,xmm1,0
    mulps xmm2,xmm1
    addps xmm0,xmm2
    movups xmm2,XMMWORD PTR [rcx+B_AX2]
    andps xmm2,XMMWORD PTR pAbs
    movss xmm1,REAL4 PTR [rcx+B_HALF+8]
    shufps xmm1,xmm1,0
    mulps xmm2,xmm1
    addps xmm0,xmm2
    movups xmm1,XMMWORD PTR [rcx+B_POS]
    movaps xmm2,xmm1
    subps xmm1,xmm0
    addps xmm2,xmm0
    movups XMMWORD PTR [rcx+B_LOW],xmm1
    movups XMMWORD PTR [rcx+B_HIGH],xmm2
    add rcx,256
    dec edx
    jnz prepare_body
prepare_done:
    ret
PhysicsPrepare ENDP

; World-space inverse inertia tensor times vector. RCX=body RDX=vec R8=out.
InverseInertia PROC
    VDOT xmm0,rcx+B_AX0,rdx,xmm1
    mulss xmm0,REAL4 PTR [rcx+B_INERTIA]
    shufps xmm0,xmm0,0
    movups xmm3,XMMWORD PTR [rcx+B_AX0]
    mulps xmm3,xmm0
    VDOT xmm0,rcx+B_AX1,rdx,xmm1
    mulss xmm0,REAL4 PTR [rcx+B_INERTIA+4]
    shufps xmm0,xmm0,0
    movups xmm2,XMMWORD PTR [rcx+B_AX1]
    mulps xmm2,xmm0
    addps xmm3,xmm2
    VDOT xmm0,rcx+B_AX2,rdx,xmm1
    mulss xmm0,REAL4 PTR [rcx+B_INERTIA+8]
    shufps xmm0,xmm0,0
    movups xmm2,XMMWORD PTR [rcx+B_AX2]
    mulps xmm2,xmm0
    addps xmm3,xmm2
    movups XMMWORD PTR [r8],xmm3
    ret
InverseInertia ENDP

; RCX=bodies EDX=count R8={gravity.xyz,dt}. Semi-implicit Euler, quaternion spin.
PhysicsIntegrate PROC FRAME
    push rbx
    .pushreg rbx
    push rsi
    .pushreg rsi
    push rdi
    .pushreg rdi
    sub rsp,60h
    .allocstack 60h
    .endprolog
    mov rbx,rcx
    mov esi,edx
    mov rdi,r8
    test esi,esi
    jz integrate_end
integrate_next:
    mov DWORD PTR [rbx+B_GROUND],0
    movups xmm0,XMMWORD PTR [rbx+B_POS]
    movups XMMWORD PTR [rbx+B_PREVIOUS],xmm0
    mov eax,DWORD PTR [rbx+B_FLAGS]
    and eax,3
    cmp eax,3
    jne integrate_clear
    movss xmm1,REAL4 PTR [rbx+B_MASS]
    shufps xmm1,xmm1,0
    movups xmm0,XMMWORD PTR [rbx+B_FORCE]
    mulps xmm0,xmm1
    movups xmm2,XMMWORD PTR [rdi]
    movss xmm1,REAL4 PTR [rbx+B_GRAVITY]
    shufps xmm1,xmm1,0
    mulps xmm2,xmm1
    addps xmm0,xmm2
    movss xmm1,REAL4 PTR [rdi+12]
    shufps xmm1,xmm1,0
    mulps xmm0,xmm1
    addps xmm0,XMMWORD PTR [rbx+B_VEL]
    movss xmm2,REAL4 PTR [rbx+B_DRAG]
    mulss xmm2,REAL4 PTR [rdi+12]
    addss xmm2,pOne
    shufps xmm2,xmm2,0
    divps xmm0,xmm2
    movups XMMWORD PTR [rbx+B_VEL],xmm0
    mulps xmm0,xmm1
    addps xmm0,XMMWORD PTR [rbx+B_POS]
    movups XMMWORD PTR [rbx+B_POS],xmm0
    mov DWORD PTR [rbx+B_VEL+12],0
    mov DWORD PTR [rbx+B_POS+12],0
    test DWORD PTR [rbx+B_FLAGS],4
    jnz integrate_freeze
    mov rcx,rbx
    lea rdx,[rbx+B_TORQUE]
    lea r8,[rsp+20h]
    call InverseInertia
    movups xmm0,XMMWORD PTR [rsp+20h]
    movss xmm1,REAL4 PTR [rdi+12]
    shufps xmm1,xmm1,0
    mulps xmm0,xmm1
    addps xmm0,XMMWORD PTR [rbx+B_OMEGA]
    movss xmm2,REAL4 PTR [rbx+B_ADRAG]
    mulss xmm2,REAL4 PTR [rdi+12]
    addss xmm2,pOne
    shufps xmm2,xmm2,0
    divps xmm0,xmm2
    movups XMMWORD PTR [rbx+B_OMEGA],xmm0
    mov DWORD PTR [rbx+B_OMEGA+12],0
    VCROSS xmm0,rbx+B_OMEGA,rbx+B_QUAT,xmm1,xmm2
    movss xmm1,REAL4 PTR [rbx+B_QUAT+12]
    shufps xmm1,xmm1,0
    mulps xmm1,XMMWORD PTR [rbx+B_OMEGA]
    addps xmm0,xmm1
    movups XMMWORD PTR [rsp+20h],xmm0
    VDOT xmm0,rbx+B_OMEGA,rbx+B_QUAT,xmm1
    xorps xmm0,XMMWORD PTR pSign
    movss REAL4 PTR [rsp+2Ch],xmm0
    movss xmm1,REAL4 PTR [rdi+12]
    mulss xmm1,pHalf
    shufps xmm1,xmm1,0
    movups xmm0,XMMWORD PTR [rsp+20h]
    mulps xmm0,xmm1
    addps xmm0,XMMWORD PTR [rbx+B_QUAT]
    movups XMMWORD PTR [rsp+20h],xmm0
    VDOT xmm0,rsp+20h,rsp+20h,xmm1
    maxss xmm0,pEpsilon
    sqrtss xmm0,xmm0
    shufps xmm0,xmm0,0
    movups xmm1,XMMWORD PTR [rsp+20h]
    divps xmm1,xmm0
    movups XMMWORD PTR [rbx+B_QUAT],xmm1
    jmp integrate_clear
integrate_freeze:
    xorps xmm0,xmm0
    movups XMMWORD PTR [rbx+B_OMEGA],xmm0
integrate_clear:
    xorps xmm0,xmm0
    movups XMMWORD PTR [rbx+B_FORCE],xmm0
    movups XMMWORD PTR [rbx+B_TORQUE],xmm0
    add rbx,256
    dec esi
    jnz integrate_next
integrate_end:
    add rsp,60h
    pop rdi
    pop rsi
    pop rbx
    ret
PhysicsIntegrate ENDP

; SAT context: A*0 B/tri*8 kind16 depth24 normal32 axis48 scratch64 centerDot80.
; RCX=context, RDX=axis. Returns zero for separation, one otherwise.
TestAxis PROC
    mov r10,rcx
    mov r11,QWORD PTR [rcx]
    mov r8,QWORD PTR [rcx+8]
    VDOT xmm0,rdx,rdx,xmm1
    comiss xmm0,pEpsilon
    jb axis_skip
    sqrtss xmm0,xmm0
    shufps xmm0,xmm0,0
    movups xmm1,XMMWORD PTR [rdx]
    divps xmm1,xmm0
    movups XMMWORD PTR [r10+48],xmm1
    VDOT xmm0,r10+48,r11+B_AX0,xmm1
    andps xmm0,XMMWORD PTR pAbs
    mulss xmm0,REAL4 PTR [r11+B_HALF]
    movaps xmm3,xmm0
    VDOT xmm0,r10+48,r11+B_AX1,xmm1
    andps xmm0,XMMWORD PTR pAbs
    mulss xmm0,REAL4 PTR [r11+B_HALF+4]
    addss xmm3,xmm0
    VDOT xmm0,r10+48,r11+B_AX2,xmm1
    andps xmm0,XMMWORD PTR pAbs
    mulss xmm0,REAL4 PTR [r11+B_HALF+8]
    addss xmm3,xmm0
    cmp DWORD PTR [r10+16],1
    je axis_triangle
    VDOT xmm0,r10+48,r8+B_AX0,xmm1
    andps xmm0,XMMWORD PTR pAbs
    mulss xmm0,REAL4 PTR [r8+B_HALF]
    movaps xmm4,xmm0
    VDOT xmm0,r10+48,r8+B_AX1,xmm1
    andps xmm0,XMMWORD PTR pAbs
    mulss xmm0,REAL4 PTR [r8+B_HALF+4]
    addss xmm4,xmm0
    VDOT xmm0,r10+48,r8+B_AX2,xmm1
    andps xmm0,XMMWORD PTR pAbs
    mulss xmm0,REAL4 PTR [r8+B_HALF+8]
    addss xmm4,xmm0
    movups xmm0,XMMWORD PTR [r8+B_POS]
    subps xmm0,XMMWORD PTR [r11+B_POS]
    movups XMMWORD PTR [r10+64],xmm0
    VDOT xmm0,r10+48,r10+64,xmm1
    movaps xmm2,xmm0
    andps xmm0,XMMWORD PTR pAbs
    addss xmm3,xmm4
    subss xmm3,xmm0
    xorps xmm0,xmm0
    comiss xmm3,xmm0
    jb axis_separate
    comiss xmm3,REAL4 PTR [r10+24]
    jae axis_skip
    movups xmm1,XMMWORD PTR [r10+48]
    comiss xmm2,xmm0
    jbe axis_save
    xorps xmm1,XMMWORD PTR pSign
    jmp axis_save
axis_triangle:
    VDOT xmm0,r10+48,r11+B_POS,xmm1
    movss REAL4 PTR [r10+80],xmm0
    VDOT xmm0,r10+48,r8,xmm1
    subss xmm0,REAL4 PTR [r10+80]
    movaps xmm2,xmm0
    movaps xmm4,xmm0
    VDOT xmm0,r10+48,r8+16,xmm1
    subss xmm0,REAL4 PTR [r10+80]
    minss xmm2,xmm0
    maxss xmm4,xmm0
    VDOT xmm0,r10+48,r8+32,xmm1
    subss xmm0,REAL4 PTR [r10+80]
    minss xmm2,xmm0
    maxss xmm4,xmm0
    ; d_negative = radius - tri_min, d_positive = tri_max + radius.
    movaps xmm5,xmm3
    subss xmm5,xmm2
    addss xmm3,xmm4
    xorps xmm0,xmm0
    comiss xmm5,xmm0
    jb axis_separate
    comiss xmm3,xmm0
    jb axis_separate
    movups xmm1,XMMWORD PTR [r10+48]
    comiss xmm3,xmm5
    jbe axis_tri_min
    movaps xmm3,xmm5
    xorps xmm1,XMMWORD PTR pSign
axis_tri_min:
    comiss xmm3,REAL4 PTR [r10+24]
    jae axis_skip
axis_save:
    movss REAL4 PTR [r10+24],xmm3
    movups XMMWORD PTR [r10+32],xmm1
    mov DWORD PTR [r10+44],0
axis_skip:
    mov eax,1
    ret
axis_separate:
    xor eax,eax
    ret
TestAxis ENDP

; Support point averaged across a supporting face/edge, not an arbitrary corner.
; RCX=body RDX=normal R8=out R9D=0 positive, 1 negative.
SupportPoint PROC
    movups xmm3,XMMWORD PTR [rcx+B_POS]
    xor eax,eax
support_axis:
    mov r10,rax
    shl r10,4
    lea r11,[rcx+r10+B_AX0]
    VDOT xmm0,r11,rdx,xmm1
    movaps xmm2,xmm0
    andps xmm0,XMMWORD PTR pAbs
    comiss xmm0,pContactEps
    jb support_next
    movss xmm0,REAL4 PTR [rcx+rax*4+B_HALF]
    xorps xmm1,xmm1
    comiss xmm2,xmm1
    jae support_direction
    xorps xmm0,XMMWORD PTR pSign
support_direction:
    test r9d,r9d
    jz support_add
    xorps xmm0,XMMWORD PTR pSign
support_add:
    shufps xmm0,xmm0,0
    mulps xmm0,XMMWORD PTR [r11]
    addps xmm3,xmm0
support_next:
    inc eax
    cmp eax,3
    jb support_axis
    movups XMMWORD PTR [r8],xmm3
    ret
SupportPoint ENDP

; Finish a geometric Contact, already containing a,b,normal,depth. EDX=1 triangle.
FinishContact PROC FRAME
    push rbx
    .pushreg rbx
    sub rsp,40h
    .allocstack 40h
    .endprolog
    mov rbx,rcx
    mov DWORD PTR [rsp+30h],edx
    mov rcx,QWORD PTR [rbx]
    lea rdx,[rbx+16]
    lea r8,[rbx+32]
    mov r9d,1
    call SupportPoint
    cmp DWORD PTR [rsp+30h],1
    je finish_material
    mov rcx,QWORD PTR [rbx+8]
    lea rdx,[rbx+16]
    lea r8,[rsp+20h]
    xor r9d,r9d
    call SupportPoint
    movups xmm0,XMMWORD PTR [rsp+20h]
    addps xmm0,XMMWORD PTR [rbx+32]
    movss xmm1,pHalf
    shufps xmm1,xmm1,0
    mulps xmm0,xmm1
    movups XMMWORD PTR [rbx+32],xmm0
finish_material:
    mov rax,QWORD PTR [rbx]
    mov rdx,QWORD PTR [rbx+8]
    movss xmm0,REAL4 PTR [rax+B_FRICTION]
    mulss xmm0,REAL4 PTR [rdx+B_FRICTION]
    sqrtss xmm0,xmm0
    movss REAL4 PTR [rbx+52],xmm0
    movss xmm0,REAL4 PTR [rax+B_BOUNCE]
    maxss xmm0,REAL4 PTR [rdx+B_BOUNCE]
    movss REAL4 PTR [rbx+56],xmm0
    mov DWORD PTR [rbx+60],0       ; accumulated normal impulse
    mov DWORD PTR [rbx+64],0       ; target separating velocity
    mov DWORD PTR [rbx+68],0       ; target initialized
    mov QWORD PTR [rbx+72],0
    add rsp,40h
    pop rbx
    ret
FinishContact ENDP

; RCX=A RDX=B R8=Contact. Fifteen OBB separating axes.
PhysicsBoxBox PROC FRAME
    push rbx
    .pushreg rbx
    push rsi
    .pushreg rsi
    push rdi
    .pushreg rdi
    push r12
    .pushreg r12
    push r13
    .pushreg r13
    sub rsp,0B0h
    .allocstack 0B0h
    .endprolog
    mov rbx,rcx
    mov rsi,rdx
    mov rdi,r8
    mov [rsp+20h],rbx
    mov [rsp+28h],rsi
    mov DWORD PTR [rsp+30h],0
    movss xmm0,pHuge
    movss REAL4 PTR [rsp+38h],xmm0
    xor r12d,r12d
box_faces:
    lea rcx,[rsp+20h]
    lea rdx,[rbx+r12+B_AX0]
    call TestAxis
    test eax,eax
    jz box_done
    lea rcx,[rsp+20h]
    lea rdx,[rsi+r12+B_AX0]
    call TestAxis
    test eax,eax
    jz box_done
    add r12d,16
    cmp r12d,48
    jb box_faces
    xor r12d,r12d
box_cross_i:
    xor r13d,r13d
box_cross_j:
    lea r10,[rbx+r12+B_AX0]
    lea r11,[rsi+r13+B_AX0]
    VCROSS xmm0,r10,r11,xmm1,xmm2
    movups XMMWORD PTR [rsp+80h],xmm0
    lea rcx,[rsp+20h]
    lea rdx,[rsp+80h]
    call TestAxis
    test eax,eax
    jz box_done
    add r13d,16
    cmp r13d,48
    jb box_cross_j
    add r12d,16
    cmp r12d,48
    jb box_cross_i
    mov QWORD PTR [rdi],rbx
    mov QWORD PTR [rdi+8],rsi
    movups xmm0,XMMWORD PTR [rsp+40h]
    movups XMMWORD PTR [rdi+16],xmm0
    movss xmm0,REAL4 PTR [rsp+38h]
    movss REAL4 PTR [rdi+48],xmm0
    mov rcx,rdi
    xor edx,edx
    call FinishContact
    mov eax,1
box_done:
    add rsp,0B0h
    pop r13
    pop r12
    pop rdi
    pop rsi
    pop rbx
    ret
PhysicsBoxBox ENDP

; RCX=box RDX=world Triangle R8=Contact R9=static/kinematic surface Body.
PhysicsBoxTriangle PROC FRAME
    push rbx
    .pushreg rbx
    push rsi
    .pushreg rsi
    push rdi
    .pushreg rdi
    push r12
    .pushreg r12
    push r13
    .pushreg r13
    sub rsp,0E0h
    .allocstack 0E0h
    .endprolog
    mov rbx,rcx
    mov rsi,rdx
    mov rdi,r8
    mov [rsp+0D0h],r9
    mov [rsp+20h],rbx
    mov [rsp+28h],rsi
    mov DWORD PTR [rsp+30h],1
    movss xmm0,pHuge
    movss REAL4 PTR [rsp+38h],xmm0
    movups xmm0,XMMWORD PTR [rsi+16]
    subps xmm0,XMMWORD PTR [rsi]
    movups XMMWORD PTR [rsp+80h],xmm0
    movups xmm0,XMMWORD PTR [rsi+32]
    subps xmm0,XMMWORD PTR [rsi+16]
    movups XMMWORD PTR [rsp+90h],xmm0
    movups xmm0,XMMWORD PTR [rsi]
    subps xmm0,XMMWORD PTR [rsi+32]
    movups XMMWORD PTR [rsp+0A0h],xmm0
    VCROSS xmm0,rsp+80h,rsp+90h,xmm1,xmm2
    movups XMMWORD PTR [rsp+0B0h],xmm0
    VDOT xmm0,rsp+0B0h,rsp+0B0h,xmm1
    comiss xmm0,pEpsilon
    jb tri_no_hit                 ; degenerate triangle
    lea rcx,[rsp+20h]
    lea rdx,[rsp+0B0h]
    call TestAxis
    test eax,eax
    jz tri_done
    xor r12d,r12d
tri_axis_i:
    lea rcx,[rsp+20h]
    lea rdx,[rbx+r12+B_AX0]
    call TestAxis
    test eax,eax
    jz tri_done
    xor r13d,r13d
tri_axis_j:
    lea r10,[rbx+r12+B_AX0]
    lea r11,[rsp+r13+80h]
    VCROSS xmm0,r10,r11,xmm1,xmm2
    movups XMMWORD PTR [rsp+0B0h],xmm0
    lea rcx,[rsp+20h]
    lea rdx,[rsp+0B0h]
    call TestAxis
    test eax,eax
    jz tri_done
    add r13d,16
    cmp r13d,48
    jb tri_axis_j
    add r12d,16
    cmp r12d,48
    jb tri_axis_i
    mov [rdi],rbx
    mov rax,[rsp+0D0h]
    mov [rdi+8],rax
    movups xmm0,XMMWORD PTR [rsp+40h]
    movups XMMWORD PTR [rdi+16],xmm0
    movss xmm0,REAL4 PTR [rsp+38h]
    movss REAL4 PTR [rdi+48],xmm0
    mov rcx,rdi
    mov edx,1
    call FinishContact
    mov eax,1
    jmp tri_done
tri_no_hit:
    xor eax,eax
tri_done:
    add rsp,0E0h
    pop r13
    pop r12
    pop rdi
    pop rsi
    pop rbx
    ret
PhysicsBoxTriangle ENDP

; RCX=Pair{Body*a,Body*b}[] EDX=count R8=Contact[] R9D=capacity.
PhysicsBoxContacts PROC FRAME
    push rbx
    .pushreg rbx
    push rsi
    .pushreg rsi
    push rdi
    .pushreg rdi
    push r12
    .pushreg r12
    push r13
    .pushreg r13
    sub rsp,20h
    .allocstack 20h
    .endprolog
    mov rbx,rcx
    mov esi,edx
    mov rdi,r8
    mov r12d,r9d
    xor r13d,r13d
pair_loop:
    test esi,esi
    jz pair_end
    cmp r13d,r12d
    jae pair_end
    mov rcx,[rbx]
    mov rdx,[rbx+8]
    imul eax,r13d,80
    lea r8,[rdi+rax]
    call PhysicsBoxBox
    add r13d,eax
    add rbx,16
    dec esi
    jmp pair_loop
pair_end:
    mov eax,r13d
    add rsp,20h
    pop r13
    pop r12
    pop rdi
    pop rsi
    pop rbx
    ret
PhysicsBoxContacts ENDP

; Mesh: nodes*0 triangles*8 surfaceBody*16 pad24 position32 basis48/64/80,
; inverse transform rows96/112/128. Nodes: min0 max16 left32 right36 first40 count44.
; RCX=box RDX=mesh R8=out contacts R9D=capacity. Local BVH, world narrowphase.
PhysicsMeshContacts PROC FRAME
    push rbx
    .pushreg rbx
    push rsi
    .pushreg rsi
    push rdi
    .pushreg rdi
    push r12
    .pushreg r12
    push r13
    .pushreg r13
    push r14
    .pushreg r14
    push r15
    .pushreg r15
    sub rsp,380h
    .allocstack 380h
    .endprolog
    mov rbx,rcx
    mov rsi,rdx
    mov rdi,r8
    mov r12d,r9d
    xor r13d,r13d
    test r12d,r12d
    jz mesh_end
    cmp QWORD PTR [rsi],0
    je mesh_end
    movups xmm0,XMMWORD PTR [rbx+B_POS]
    subps xmm0,XMMWORD PTR [rsi+32]
    movups XMMWORD PTR [rsp+80h],xmm0
    xor r14d,r14d
mesh_bounds:
    mov eax,r14d
    shl eax,4
    lea r10,[rsi+rax+96]
    VDOT xmm0,r10,rsp+80h,xmm1
    movaps xmm4,xmm0
    VDOT xmm0,r10,rbx+B_AX0,xmm1
    andps xmm0,XMMWORD PTR pAbs
    mulss xmm0,REAL4 PTR [rbx+B_HALF]
    movaps xmm3,xmm0
    VDOT xmm0,r10,rbx+B_AX1,xmm1
    andps xmm0,XMMWORD PTR pAbs
    mulss xmm0,REAL4 PTR [rbx+B_HALF+4]
    addss xmm3,xmm0
    VDOT xmm0,r10,rbx+B_AX2,xmm1
    andps xmm0,XMMWORD PTR pAbs
    mulss xmm0,REAL4 PTR [rbx+B_HALF+8]
    addss xmm3,xmm0
    movaps xmm0,xmm4
    subss xmm0,xmm3
    addss xmm4,xmm3
    movss REAL4 PTR [rsp+r14*4+20h],xmm0
    movss REAL4 PTR [rsp+r14*4+30h],xmm4
    inc r14d
    cmp r14d,3
    jb mesh_bounds
    mov DWORD PTR [rsp+100h],0
    mov r15d,1
mesh_node:
    test r15d,r15d
    jz mesh_end
    dec r15d
    mov eax,DWORD PTR [rsp+r15*4+100h]
    imul rax,rax,48
    add rax,QWORD PTR [rsi]
    xor ecx,ecx
mesh_node_axis:
    movss xmm0,REAL4 PTR [rax+rcx*4]
    comiss xmm0,REAL4 PTR [rsp+rcx*4+30h]
    ja mesh_node
    movss xmm0,REAL4 PTR [rax+rcx*4+16]
    comiss xmm0,REAL4 PTR [rsp+rcx*4+20h]
    jb mesh_node
    inc ecx
    cmp ecx,3
    jb mesh_node_axis
    mov ecx,DWORD PTR [rax+44]
    test ecx,ecx
    jnz mesh_leaf
    ; Balanced builder limits depth to <=64. Defensive bound on stack writes.
    cmp r15d,126
    ja mesh_end
    mov ecx,DWORD PTR [rax+32]
    mov DWORD PTR [rsp+r15*4+100h],ecx
    inc r15d
    mov ecx,DWORD PTR [rax+36]
    mov DWORD PTR [rsp+r15*4+100h],ecx
    inc r15d
    jmp mesh_node
mesh_leaf:
    mov DWORD PTR [rsp+94h],ecx
    mov eax,DWORD PTR [rax+40]
    mov DWORD PTR [rsp+90h],eax
mesh_triangle:
    mov eax,DWORD PTR [rsp+90h]
    imul rax,rax,48
    add rax,QWORD PTR [rsi+8]
    xor ecx,ecx
mesh_vertex:
    movss xmm0,REAL4 PTR [rax+rcx]
    shufps xmm0,xmm0,0
    mulps xmm0,XMMWORD PTR [rsi+48]
    movss xmm1,REAL4 PTR [rax+rcx+4]
    shufps xmm1,xmm1,0
    mulps xmm1,XMMWORD PTR [rsi+64]
    addps xmm0,xmm1
    movss xmm1,REAL4 PTR [rax+rcx+8]
    shufps xmm1,xmm1,0
    mulps xmm1,XMMWORD PTR [rsi+80]
    addps xmm0,xmm1
    addps xmm0,XMMWORD PTR [rsi+32]
    movups XMMWORD PTR [rsp+rcx+40h],xmm0
    add ecx,16
    cmp ecx,48
    jb mesh_vertex
    mov rcx,rbx
    lea rdx,[rsp+40h]
    imul eax,r13d,80
    lea r8,[rdi+rax]
    mov r9,QWORD PTR [rsi+16]
    call PhysicsBoxTriangle
    add r13d,eax
    cmp r13d,r12d
    jae mesh_end
    inc DWORD PTR [rsp+90h]
    dec DWORD PTR [rsp+94h]
    jnz mesh_triangle
    jmp mesh_node
mesh_end:
    mov eax,r13d
    add rsp,380h
    pop r15
    pop r14
    pop r13
    pop r12
    pop rdi
    pop rsi
    pop rbx
    ret
PhysicsMeshContacts ENDP

; Velocity at a world point: v + omega cross (point-COM). XMM0=result.
PointVelocity PROC FRAME
    sub rsp,28h
    .allocstack 28h
    .endprolog
    movups xmm0,XMMWORD PTR [rdx]
    subps xmm0,XMMWORD PTR [rcx+B_POS]
    movups XMMWORD PTR [rsp],xmm0
    VCROSS xmm0,rcx+B_OMEGA,rsp,xmm1,xmm2
    addps xmm0,XMMWORD PTR [rcx+B_VEL]
    add rsp,28h
    ret
PointVelocity ENDP

; RCX=contact, R8=out, relative point velocity A-B.
ContactVelocity PROC FRAME
    push rbx
    .pushreg rbx
    push rsi
    .pushreg rsi
    sub rsp,38h
    .allocstack 38h
    .endprolog
    mov rbx,rcx
    mov rsi,r8
    mov rcx,[rbx]
    lea rdx,[rbx+32]
    call PointVelocity
    movups XMMWORD PTR [rsp+20h],xmm0
    mov rcx,[rbx+8]
    lea rdx,[rbx+32]
    call PointVelocity
    movups xmm1,XMMWORD PTR [rsp+20h]
    subps xmm1,xmm0
    movups XMMWORD PTR [rsi],xmm1
    add rsp,38h
    pop rsi
    pop rbx
    ret
ContactVelocity ENDP

; Angular effective inverse mass along direction. RCX=body RDX=point R8=direction.
AngularDenom PROC FRAME
    push rbx
    .pushreg rbx
    push rsi
    .pushreg rsi
    push rdi
    .pushreg rdi
    sub rsp,60h
    .allocstack 60h
    .endprolog
    mov rbx,rcx
    mov rdi,r8
    movups xmm0,XMMWORD PTR [rdx]
    subps xmm0,XMMWORD PTR [rbx+B_POS]
    movups XMMWORD PTR [rsp+20h],xmm0
    VCROSS xmm0,rsp+20h,rdi,xmm1,xmm2
    movups XMMWORD PTR [rsp+30h],xmm0
    mov rcx,rbx
    lea rdx,[rsp+30h]
    lea r8,[rsp+40h]
    call InverseInertia
    VCROSS xmm0,rsp+40h,rsp+20h,xmm1,xmm2
    movups XMMWORD PTR [rsp+50h],xmm0
    VDOT xmm0,rsp+50h,rdi,xmm1
    add rsp,60h
    pop rdi
    pop rsi
    pop rbx
    ret
AngularDenom ENDP

; RCX=contact RDX=direction; XMM0=total effective inverse mass.
ContactDenom PROC FRAME
    push rbx
    .pushreg rbx
    push rsi
    .pushreg rsi
    sub rsp,38h
    .allocstack 38h
    .endprolog
    mov rbx,rcx
    mov rsi,rdx
    mov rcx,[rbx]
    lea rdx,[rbx+32]
    mov r8,rsi
    call AngularDenom
    movss REAL4 PTR [rsp+20h],xmm0
    mov rcx,[rbx+8]
    lea rdx,[rbx+32]
    mov r8,rsi
    call AngularDenom
    addss xmm0,REAL4 PTR [rsp+20h]
    mov rax,[rbx]
    addss xmm0,REAL4 PTR [rax+B_MASS]
    mov rax,[rbx+8]
    addss xmm0,REAL4 PTR [rax+B_MASS]
    add rsp,38h
    pop rsi
    pop rbx
    ret
ContactDenom ENDP

; RCX=contact RDX=world impulse, +J on A and -J on B, including angular impulse.
ApplyImpulse PROC FRAME
    push rbx
    .pushreg rbx
    push rsi
    .pushreg rsi
    push rdi
    .pushreg rdi
    sub rsp,60h
    .allocstack 60h
    .endprolog
    mov rbx,rcx
    mov rsi,rdx
    xor edi,edi
impulse_body:
    mov r10,[rbx+rdi]
    movss xmm0,REAL4 PTR [r10+B_MASS]
    test edi,edi
    jz impulse_mass
    xorps xmm0,XMMWORD PTR pSign
impulse_mass:
    shufps xmm0,xmm0,0
    mulps xmm0,XMMWORD PTR [rsi]
    addps xmm0,XMMWORD PTR [r10+B_VEL]
    movups XMMWORD PTR [r10+B_VEL],xmm0
    movups xmm0,XMMWORD PTR [rbx+32]
    subps xmm0,XMMWORD PTR [r10+B_POS]
    movups XMMWORD PTR [rsp+20h],xmm0
    VCROSS xmm0,rsp+20h,rsi,xmm1,xmm2
    test edi,edi
    jz impulse_cross
    xorps xmm0,XMMWORD PTR pSign
impulse_cross:
    movups XMMWORD PTR [rsp+30h],xmm0
    mov rcx,r10
    lea rdx,[rsp+30h]
    lea r8,[rsp+40h]
    call InverseInertia
    mov r10,[rbx+rdi]
    movups xmm0,XMMWORD PTR [rsp+40h]
    addps xmm0,XMMWORD PTR [r10+B_OMEGA]
    movups XMMWORD PTR [r10+B_OMEGA],xmm0
    add edi,8
    cmp edi,16
    jb impulse_body
    add rsp,60h
    pop rdi
    pop rsi
    pop rbx
    ret
ApplyImpulse ENDP

SolveContact PROC FRAME
    push rbx
    .pushreg rbx
    sub rsp,90h
    .allocstack 90h
    .endprolog
    mov rbx,rcx
    lea r8,[rsp+20h]
    call ContactVelocity
    VDOT xmm0,rsp+20h,rbx+16,xmm1
    movss REAL4 PTR [rsp+60h],xmm0
    cmp DWORD PTR [rbx+68],0
    jne solve_target_ready
    mov DWORD PTR [rbx+68],1
    comiss xmm0,pBounceThreshold
    jae solve_target_ready
    xorps xmm0,XMMWORD PTR pSign
    mulss xmm0,REAL4 PTR [rbx+56]
    movss REAL4 PTR [rbx+64],xmm0
solve_target_ready:
    mov rcx,rbx
    lea rdx,[rbx+16]
    call ContactDenom
    comiss xmm0,pEpsilon
    jbe solve_contact_done
    movss xmm1,REAL4 PTR [rbx+64]
    subss xmm1,REAL4 PTR [rsp+60h]
    divss xmm1,xmm0
    movss xmm2,REAL4 PTR [rbx+60]
    addss xmm1,xmm2
    xorps xmm0,xmm0
    maxss xmm1,xmm0
    movss REAL4 PTR [rbx+60],xmm1
    subss xmm1,xmm2
    shufps xmm1,xmm1,0
    mulps xmm1,XMMWORD PTR [rbx+16]
    movups XMMWORD PTR [rsp+40h],xmm1
    mov rcx,rbx
    lea rdx,[rsp+40h]
    call ApplyImpulse
    ; Recompute slip after normal impulse; isotropic Coulomb friction.
    mov rcx,rbx
    lea r8,[rsp+20h]
    call ContactVelocity
    VDOT xmm0,rsp+20h,rbx+16,xmm1
    shufps xmm0,xmm0,0
    mulps xmm0,XMMWORD PTR [rbx+16]
    movups xmm1,XMMWORD PTR [rsp+20h]
    subps xmm1,xmm0
    movups XMMWORD PTR [rsp+50h],xmm1
    VDOT xmm0,rsp+50h,rsp+50h,xmm1
    comiss xmm0,pEpsilon
    jbe solve_contact_done
    sqrtss xmm0,xmm0
    movss REAL4 PTR [rsp+60h],xmm0
    shufps xmm0,xmm0,0
    movups xmm1,XMMWORD PTR [rsp+50h]
    divps xmm1,xmm0
    movups XMMWORD PTR [rsp+50h],xmm1
    mov rcx,rbx
    lea rdx,[rsp+50h]
    call ContactDenom
    comiss xmm0,pEpsilon
    jbe solve_contact_done
    movss xmm1,REAL4 PTR [rsp+60h]
    divss xmm1,xmm0
    movss xmm2,REAL4 PTR [rbx+52]
    mulss xmm2,REAL4 PTR [rbx+60]
    minss xmm1,xmm2
    xorps xmm1,XMMWORD PTR pSign
    shufps xmm1,xmm1,0
    mulps xmm1,XMMWORD PTR [rsp+50h]
    movups XMMWORD PTR [rsp+40h],xmm1
    mov rcx,rbx
    lea rdx,[rsp+40h]
    call ApplyImpulse
solve_contact_done:
    add rsp,90h
    pop rbx
    ret
SolveContact ENDP

; RCX=Contact[] EDX=count R8D=iterations. Position correction happens only once.
PhysicsSolve PROC FRAME
    push rbx
    .pushreg rbx
    push rsi
    .pushreg rsi
    push rdi
    .pushreg rdi
    push r12
    .pushreg r12
    push r13
    .pushreg r13
    sub rsp,20h
    .allocstack 20h
    .endprolog
    mov rbx,rcx
    mov esi,edx
    mov edi,r8d
    test esi,esi
    jz solve_done
    cmp edi,1
    jae solve_iter_max
    mov edi,1
solve_iter_max:
    cmp edi,32
    jbe solve_iteration
    mov edi,32
solve_iteration:
    mov r12,rbx
    mov r13d,esi
solve_velocity:
    mov rcx,r12
    call SolveContact
    add r12,80
    dec r13d
    jnz solve_velocity
    dec edi
    jnz solve_iteration
    mov r12,rbx
    mov r13d,esi
solve_positions:
    mov rax,[r12]
    mov rdx,[r12+8]
    movss xmm3,REAL4 PTR [rax+B_MASS]
    addss xmm3,REAL4 PTR [rdx+B_MASS]
    comiss xmm3,pEpsilon
    jbe solve_position_next
    movss xmm0,REAL4 PTR [r12+48]
    subss xmm0,pSlop
    xorps xmm1,xmm1
    maxss xmm0,xmm1
    mulss xmm0,pCorrection
    divss xmm0,xmm3
    shufps xmm0,xmm0,0
    mulps xmm0,XMMWORD PTR [r12+16]
    movss xmm1,REAL4 PTR [rax+B_MASS]
    shufps xmm1,xmm1,0
    mulps xmm1,xmm0
    addps xmm1,XMMWORD PTR [rax+B_POS]
    movups XMMWORD PTR [rax+B_POS],xmm1
    movss xmm1,REAL4 PTR [rdx+B_MASS]
    shufps xmm1,xmm1,0
    mulps xmm1,xmm0
    movups xmm0,XMMWORD PTR [rdx+B_POS]
    subps xmm0,xmm1
    movups XMMWORD PTR [rdx+B_POS],xmm0
    movss xmm0,REAL4 PTR [r12+20]
    comiss xmm0,pGround
    jb solve_ground_b
    mov DWORD PTR [rax+B_GROUND],1
solve_ground_b:
    xorps xmm0,XMMWORD PTR pSign
    comiss xmm0,pGround
    jb solve_position_next
    mov DWORD PTR [rdx+B_GROUND],1
solve_position_next:
    add r12,80
    dec r13d
    jnz solve_positions
solve_done:
    add rsp,20h
    pop r13
    pop r12
    pop rdi
    pop rsi
    pop rbx
    ret
PhysicsSolve ENDP
END
