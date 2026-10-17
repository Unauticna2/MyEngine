; Native scene / resource API. Called only on the WGL owner thread.
option casemap:none
EXTERN glBegin:PROC, glEnd:PROC, glNormal3f:PROC, glTexCoord2f:PROC, glVertex3f:PROC
EXTERN glGenLists:PROC, glNewList:PROC, glEndList:PROC, glDeleteLists:PROC, glCallList:PROC
EXTERN glGetError:PROC, glGenTextures:PROC, glDeleteTextures:PROC, glBindTexture:PROC
EXTERN glTexParameteri:PROC, glTexImage2D:PROC, glPixelStorei:PROC
EXTERN glPushMatrix:PROC, glPopMatrix:PROC, glTranslatef:PROC, glRotatef:PROC, glScalef:PROC
EXTERN glColor3f:PROC, glEnable:PROC, glDisable:PROC, glLightfv:PROC, glLightModelfv:PROC
EXTERN glColorMaterial:PROC, glAlphaFunc:PROC
EXTERN cameraPosition:REAL4, keyState:BYTE, hWindow:QWORD, hStopEvent:QWORD
PUBLIC NativeInit, NativeRender, ApplyLight, EngineGetRenderFlags
PUBLIC EngineGetCamera, EngineGetKeys, EngineGetLight, EngineGetDelta, EngineGetWindow
PUBLIC EngineSubmitScene, EngineCreateMesh, EngineDeleteMesh
PUBLIC EngineCreateTexture, EngineDeleteTexture, frameDelta

.data
renderFlags DWORD 0
scenePtr QWORD 0
sceneCount DWORD 0
frameDelta REAL4 0.0
lightEuler REAL4 0.0,0.0,0.0
fOne REAL4 1.0
fAlpha REAL4 0.1
ambient REAL4 0.6,0.6,0.6,1.0
positiveLight REAL4 0.4,0.4,0.4,1.0
negativeLight REAL4 -0.4,-0.4,-0.4,1.0
lightUp REAL4 0.0,1.0,0.0,0.0
lightDown REAL4 0.0,-1.0,0.0,0.0
zeroLight REAL4 0.0,0.0,0.0,1.0
.code
EngineGetRenderFlags PROC
    lea rax,renderFlags
    ret
EngineGetRenderFlags ENDP
EngineGetCamera PROC
    lea rax,cameraPosition
    ret
EngineGetCamera ENDP
EngineGetKeys PROC
    lea rax,keyState
    ret
EngineGetKeys ENDP
EngineGetLight PROC
    lea rax,lightEuler
    ret
EngineGetLight ENDP
EngineGetDelta PROC
    lea rax,frameDelta
    ret
EngineGetDelta ENDP
EngineGetWindow PROC
    mov rax,hWindow
    ret
EngineGetWindow ENDP
; RCX=contiguous array of 64-byte Entity records, EDX=count; caller owns memory.
EngineSubmitScene PROC
    cmp edx,4096
    ja submit_bad
    mov scenePtr,rcx
    mov sceneCount,edx
    mov eax,1
    ret
submit_bad:
    xor eax,eax
    ret
EngineSubmitScene ENDP

NativeInit PROC FRAME
    sub rsp,28h
    .allocstack 28h
    .endprolog
    mov ecx,0B50h                    ; GL_LIGHTING
    call glEnable
    mov ecx,4000h                    ; GL_LIGHT0
    call glEnable
    mov ecx,4001h                    ; GL_LIGHT1
    call glEnable
    mov ecx,0BA1h                    ; GL_NORMALIZE (also corrects nonuniform scale)
    call glEnable
    mov ecx,0408h                    ; GL_FRONT_AND_BACK
    mov edx,1602h                    ; GL_AMBIENT_AND_DIFFUSE
    call glColorMaterial
    mov ecx,0B57h                    ; GL_COLOR_MATERIAL
    call glEnable
    mov ecx,0B53h                    ; GL_LIGHT_MODEL_AMBIENT
    lea rdx,ambient
    call glLightModelfv
    mov ecx,4000h
    mov edx,1201h                    ; GL_DIFFUSE
    lea r8,positiveLight
    call glLightfv
    mov ecx,4001h
    mov edx,1201h
    lea r8,negativeLight
    call glLightfv
    ; 0.6 + 0.4*max(dot,0) - 0.4*max(-dot,0) = 0.6 + 0.4*dot.
    ; GL light intensities are not clamped; final lighting is clamped afterward.
    mov ecx,4000h
    mov edx,1202h                    ; GL_SPECULAR
    lea r8,zeroLight
    call glLightfv
    mov ecx,4001h
    mov edx,1202h
    lea r8,zeroLight
    call glLightfv
    mov ecx,0BC0h                    ; GL_ALPHA_TEST (cutout textures)
    call glEnable
    mov ecx,0204h                    ; GL_GREATER
    movss xmm1,fAlpha
    call glAlphaFunc
    add rsp,28h
    ret
NativeInit ENDP

; Call after view transform, before object transforms: the light stays in world space.
ApplyLight PROC FRAME
    sub rsp,28h
    .allocstack 28h
    .endprolog
    call glPushMatrix
    lea r10,lightEuler
    movss xmm0,REAL4 PTR [r10+8]
    xorps xmm1,xmm1
    xorps xmm2,xmm2
    movss xmm3,fOne
    call glRotatef
    lea r10,lightEuler
    movss xmm0,REAL4 PTR [r10+4]
    xorps xmm1,xmm1
    movss xmm2,fOne
    xorps xmm3,xmm3
    call glRotatef
    movss xmm0,lightEuler
    movss xmm1,fOne
    xorps xmm2,xmm2
    xorps xmm3,xmm3
    call glRotatef
    mov ecx,4000h
    mov edx,1203h                    ; GL_POSITION
    lea r8,lightUp
    call glLightfv
    mov ecx,4001h
    mov edx,1203h
    lea r8,lightDown
    call glLightfv
    call glPopMatrix
    add rsp,28h
    ret
ApplyLight ENDP

; RCX=vertices (xyz,nxyz,uv, stride 32), EDX=vertex count. Return list id or 0.
EngineCreateMesh PROC FRAME
    push rbx
    .pushreg rbx
    push rsi
    .pushreg rsi
    push rdi
    .pushreg rdi
    sub rsp,30h
    .allocstack 30h
    .endprolog
    mov rsi,rcx
    mov edi,edx
    xor ebx,ebx
    test rsi,rsi
    jz mesh_create_done
    test edi,edi
    jz mesh_create_done
    cmp edi,3000000
    ja mesh_create_done
    call glGetError
    mov ecx,1
    call glGenLists
    mov ebx,eax
    test eax,eax
    jz mesh_create_done
    mov ecx,eax
    mov edx,1300h
    call glNewList
    mov ecx,4
    call glBegin
mesh_create_loop:
    movss xmm0,REAL4 PTR [rsi+12]
    movss xmm1,REAL4 PTR [rsi+16]
    movss xmm2,REAL4 PTR [rsi+20]
    call glNormal3f
    movss xmm0,REAL4 PTR [rsi+24]
    movss xmm1,REAL4 PTR [rsi+28]
    call glTexCoord2f
    movss xmm0,REAL4 PTR [rsi]
    movss xmm1,REAL4 PTR [rsi+4]
    movss xmm2,REAL4 PTR [rsi+8]
    call glVertex3f
    add rsi,32
    dec edi
    jnz mesh_create_loop
    call glEnd
    call glEndList
    call glGetError
    test eax,eax
    jz mesh_create_done
    mov ecx,ebx
    mov edx,1
    call glDeleteLists
    xor ebx,ebx
mesh_create_done:
    mov eax,ebx
    add rsp,30h
    pop rdi
    pop rsi
    pop rbx
    ret
EngineCreateMesh ENDP
EngineDeleteMesh PROC FRAME
    sub rsp,28h
    .allocstack 28h
    .endprolog
    mov edx,1
    call glDeleteLists
    add rsp,28h
    ret
EngineDeleteMesh ENDP

; RCX=RGBA8 pixels, EDX=width, R8D=height. OpenGL row zero is the bottom row.
EngineCreateTexture PROC FRAME
    push rbx
    .pushreg rbx
    push rsi
    .pushreg rsi
    push rdi
    .pushreg rdi
    sub rsp,60h
    .allocstack 60h
    .endprolog
    mov rsi,rcx
    mov ebx,edx
    mov edi,r8d
    mov DWORD PTR [rsp+50h],0
    test rsi,rsi
    jz texture_done
    test ebx,ebx
    jle texture_done
    test edi,edi
    jle texture_done
    cmp ebx,4096
    ja texture_done
    cmp edi,4096
    ja texture_done
    call glGetError
    mov ecx,1
    lea rdx,[rsp+50h]
    call glGenTextures
    mov edx,[rsp+50h]
    test edx,edx
    jz texture_done
    mov ecx,0DE1h
    call glBindTexture
    mov ecx,0CF5h                    ; GL_UNPACK_ALIGNMENT
    mov edx,1
    call glPixelStorei
    mov ecx,0DE1h
    mov edx,2801h                    ; GL_TEXTURE_MIN_FILTER
    mov r8d,2601h                    ; GL_LINEAR, no mipmaps required
    call glTexParameteri
    mov ecx,0DE1h
    mov edx,2800h
    mov r8d,2601h
    call glTexParameteri
    mov ecx,0DE1h
    mov edx,2802h
    mov r8d,2901h                    ; GL_REPEAT
    call glTexParameteri
    mov ecx,0DE1h
    mov edx,2803h
    mov r8d,2901h
    call glTexParameteri
    mov ecx,0DE1h                    ; target
    xor edx,edx                      ; mip level
    mov r8d,1908h                    ; internal GL_RGBA
    mov r9d,ebx                      ; width
    mov [rsp+20h],edi                ; height
    mov QWORD PTR [rsp+28h],0         ; border
    mov QWORD PTR [rsp+30h],1908h     ; GL_RGBA
    mov QWORD PTR [rsp+38h],1401h     ; GL_UNSIGNED_BYTE
    mov [rsp+40h],rsi
    call glTexImage2D
    call glGetError
    test eax,eax
    jz texture_done
    mov ecx,1
    lea rdx,[rsp+50h]
    call glDeleteTextures
    mov DWORD PTR [rsp+50h],0
texture_done:
    mov eax,[rsp+50h]
    add rsp,60h
    pop rdi
    pop rsi
    pop rbx
    ret
EngineCreateTexture ENDP
EngineDeleteTexture PROC FRAME
    sub rsp,38h
    .allocstack 38h
    .endprolog
    mov [rsp+20h],ecx
    mov ecx,1
    lea rdx,[rsp+20h]
    call glDeleteTextures
    add rsp,38h
    ret
EngineDeleteTexture ENDP

; Entity: position[3], rotation[3], scale[3], color[3], mesh, texture, visible, w.
NativeRender PROC FRAME
    push rbx
    .pushreg rbx
    push rsi
    .pushreg rsi
    push rdi
    .pushreg rdi
    sub rsp,20h
    .allocstack 20h
    .endprolog
    cmp renderFlags,0
    jne native_done
    mov rsi,scenePtr
    mov edi,sceneCount
    test rsi,rsi
    jz native_done
    xor ebx,ebx
native_entity:
    cmp ebx,edi
    jae native_done
    cmp DWORD PTR [rsi+56],0
    je native_next
    cmp DWORD PTR [rsi+48],0
    je native_next
    call glPushMatrix
    movss xmm0,REAL4 PTR [rsi]
    movss xmm1,REAL4 PTR [rsi+4]
    movss xmm2,REAL4 PTR [rsi+8]
    call glTranslatef
    movss xmm0,REAL4 PTR [rsi+20]
    xorps xmm1,xmm1
    xorps xmm2,xmm2
    movss xmm3,fOne
    call glRotatef
    movss xmm0,REAL4 PTR [rsi+16]
    xorps xmm1,xmm1
    movss xmm2,fOne
    xorps xmm3,xmm3
    call glRotatef
    movss xmm0,REAL4 PTR [rsi+12]
    movss xmm1,fOne
    xorps xmm2,xmm2
    xorps xmm3,xmm3
    call glRotatef
    movss xmm0,REAL4 PTR [rsi+24]
    movss xmm1,REAL4 PTR [rsi+28]
    movss xmm2,REAL4 PTR [rsi+32]
    call glScalef
    movss xmm0,REAL4 PTR [rsi+36]
    movss xmm1,REAL4 PTR [rsi+40]
    movss xmm2,REAL4 PTR [rsi+44]
    call glColor3f
    cmp DWORD PTR [rsi+52],0
    je native_untextured
    mov ecx,0DE1h
    call glEnable
    mov ecx,0DE1h
    mov edx,[rsi+52]
    call glBindTexture
    jmp native_draw
native_untextured:
    mov ecx,0DE1h
    call glDisable
native_draw:
    mov ecx,[rsi+48]
    call glCallList
    call glPopMatrix
native_next:
    add rsi,64
    inc ebx
    jmp native_entity
native_done:
    add rsp,20h
    pop rdi
    pop rsi
    pop rbx
    ret
NativeRender ENDP
END
