; MyEngine 2. Windows x64 / MASM ml64. GL 1.1 polygons + GL 2.1 voxel pass.
; Main thread: window + input. Worker: scene loading, camera system, rendering.
; All OpenGL calls stay on one worker thread. No CRT or extra DLLs to distribute.
option casemap:none

EXTERN GetModuleHandleA:PROC, ExitProcess:PROC, GetTickCount64:PROC
EXTERN CreateThread:PROC, CreateEventA:PROC, SetEvent:PROC
EXTERN WaitForSingleObject:PROC, CloseHandle:PROC
EXTERN RegisterClassExA:PROC, CreateWindowExA:PROC, DefWindowProcA:PROC
EXTERN ShowWindow:PROC, UpdateWindow:PROC, DestroyWindow:PROC
EXTERN GetMessageA:PROC, TranslateMessage:PROC, DispatchMessageA:PROC
EXTERN LoadIconA:PROC, SetFocus:PROC
EXTERN PostQuitMessage:PROC, PostMessageA:PROC, LoadCursorA:PROC
EXTERN SetCapture:PROC, ReleaseCapture:PROC, MessageBoxA:PROC, MessageBoxW:PROC
EXTERN GetDC:PROC, ReleaseDC:PROC
EXTERN ChoosePixelFormat:PROC, SetPixelFormat:PROC, SwapBuffers:PROC
EXTERN wglCreateContext:PROC, wglMakeCurrent:PROC, wglDeleteContext:PROC
EXTERN glClearColor:PROC, glClear:PROC, glEnable:PROC, glViewport:PROC
EXTERN glMatrixMode:PROC, glLoadIdentity:PROC, glFrustum:PROC
EXTERN glTranslatef:PROC, glRotatef:PROC, glBegin:PROC, glEnd:PROC
EXTERN glColor3f:PROC, glVertex3f:PROC
EXTERN glCallList:PROC, glPushMatrix:PROC, glPopMatrix:PROC
EXTERN PythonStart:PROC, PythonFrame:PROC, PythonStop:PROC, PythonDraw:PROC
EXTERN NativeInit:PROC, NativeRender:PROC, ApplyLight:PROC, frameDelta:REAL4
EXTERN UpdateCamera:PROC, cameraPosition:REAL4, cameraPitch:REAL4, cameraYaw:REAL4
EXTERN controlBits:DWORD, mouseDX:DWORD, mouseDY:DWORD, resetRequest:DWORD, runtimeFlags:DWORD
PUBLIC hStopEvent, hWindow, keyState, EnginePollWindowCommand

WM_DESTROY       EQU 0002h
WM_SIZE          EQU 0005h
WM_KILLFOCUS     EQU 0008h
WM_CLOSE         EQU 0010h
WM_ERASEBKGND    EQU 0014h
WM_KEYDOWN       EQU 0100h
WM_KEYUP         EQU 0101h
WM_MOUSEMOVE     EQU 0200h
WM_RBUTTONDOWN   EQU 0204h ; right mouse button
WM_RBUTTONUP     EQU 0205h ; right mouse button
WM_CAPTURECHANGED EQU 0215h
WM_RENDER_DONE   EQU 8001h
GL_PROJECTION    EQU 1701h
GL_MODELVIEW     EQU 1700h
GL_DEPTH_TEST    EQU 0B71h

WNDCLASSEXA STRUCT 8
    cbSize          DWORD ?
    style           DWORD ?
    lpfnWndProc     QWORD ?
    cbClsExtra      DWORD ?
    cbWndExtra      DWORD ?
    hInstance       QWORD ?
    hIcon           QWORD ?
    hCursor         QWORD ?
    hbrBackground   QWORD ?
    lpszMenuName    QWORD ?
    lpszClassName   QWORD ?
    hIconSm         QWORD ?
WNDCLASSEXA ENDS

.data
className       BYTE "UnauticnaAsmMapEngine",0
windowTitle     BYTE "MyEngine 2",0
startupError    BYTE "Could not create the window, event, or render thread.",0
dcError         BYTE "GetDC failed.",0
pixelError      BYTE "ChoosePixelFormat / SetPixelFormat failed.",0
contextError    BYTE "Could not create or activate an OpenGL context.",0
pythonError BYTE "Python startup/update failed. Editor: run setup_python.cmd. Game: keep Data beside EXE. Logs: %LOCALAPPDATA%/MyEngine2 or project/.myengine.",0

ALIGN 8
windowClass     WNDCLASSEXA <80,23h,0,0,0,0,0,0,0,0,0,0>
hInstance       QWORD 0
hWindow         QWORD 0
hStopEvent      QWORD 0
hRenderThread   QWORD 0
hDeviceContext  QWORD 0
hGLContext      QWORD 0
renderError     QWORD 0
threadId        DWORD 0
clientWidth     DWORD 960
clientHeight    DWORD 640

; Input mailbox: naturally aligned integers, UI producer / worker consumer.
ALIGN 4
ALIGN 4
windowCommand   DWORD 0
keyState        BYTE 256 DUP(0)
dragging        DWORD 0             ; UI thread only
oldMouseX       DWORD 0             ; UI thread only
oldMouseY       DWORD 0             ; UI thread only

; Camera and scene components are defined in Camera.asm and Scene.asm.
fOne            REAL4 1.0
fMillis         REAL4 0.001
ALIGN 8
dTop            REAL8 0.0577350269189626 ; near * tan(60 degree vertical FOV / 2)
dBottom         REAL8 -0.0577350269189626
dNear           REAL8 0.1
dFar            REAL8 2000.0

; PIXELFORMATDESCRIPTOR is exactly 40 bytes. Unspecified fields stay zero.
pixelFormat     BYTE 40 DUP(0)
ALIGN 8
messageBuffer   BYTE 48 DUP(0)       ; sizeof(MSG) on Windows x64

.code

; Win64 ABI: reserve shadow space and keep RSP 16-byte aligned at every CALL.
main PROC FRAME
    sub rsp,88h
    .allocstack 88h
    .endprolog
    xor ecx,ecx
    call GetModuleHandleA
    mov hInstance,rax
    mov windowClass.hInstance,rax
    mov rcx,rax
    mov edx,101
    call LoadIconA
    mov windowClass.hIcon,rax
    mov windowClass.hIconSm,rax
    lea rax,WndProc
    mov windowClass.lpfnWndProc,rax
    lea rax,className
    mov windowClass.lpszClassName,rax
    xor ecx,ecx
    mov edx,32512                    ; IDC_ARROW
    call LoadCursorA
    mov windowClass.hCursor,rax
    xor ecx,ecx
    mov edx,1                        ; manual-reset stop event
    xor r8d,r8d
    xor r9d,r9d
    call CreateEventA
    mov hStopEvent,rax
    test rax,rax
    jz main_failed
    lea rcx,windowClass
    call RegisterClassExA
    test eax,eax
    jz main_failed
    xor ecx,ecx
    lea rdx,className
    lea r8,windowTitle
    mov r9d,06CF0000h                ; OVERLAPPEDWINDOW | CLIPCHILDREN | CLIPSIBLINGS
    mov DWORD PTR [rsp+20h],80000000h ; CW_USEDEFAULT x
    mov DWORD PTR [rsp+28h],80000000h ; CW_USEDEFAULT y
    mov QWORD PTR [rsp+30h],1000
    mov QWORD PTR [rsp+38h],720
    mov QWORD PTR [rsp+40h],0
    mov QWORD PTR [rsp+48h],0
    mov rax,hInstance
    mov [rsp+50h],rax
    mov QWORD PTR [rsp+58h],0
    call CreateWindowExA
    mov hWindow,rax
    test rax,rax
    jz main_failed
    mov rcx,rax
    mov edx,5                        ; SW_SHOW
    call ShowWindow
    mov rcx,hWindow
    call UpdateWindow
    xor ecx,ecx
    xor edx,edx
    lea r8,RenderThread
    xor r9d,r9d
    mov QWORD PTR [rsp+20h],0
    lea rax,threadId
    mov [rsp+28h],rax
    call CreateThread
    mov hRenderThread,rax
    test rax,rax
    jz main_failed
main_messages:
    lea rcx,messageBuffer
    xor edx,edx
    xor r8d,r8d
    xor r9d,r9d
    call GetMessageA
    test eax,eax
    jle main_cleanup
    lea rcx,messageBuffer
    call TranslateMessage
    lea rcx,messageBuffer
    call DispatchMessageA
    jmp main_messages
main_failed:
    xor ecx,ecx
    lea rdx,startupError
    lea r8,className
    mov r9d,10h
    call MessageBoxA
main_cleanup:
    mov rcx,hStopEvent
    test rcx,rcx
    jz main_close_thread
    call SetEvent
main_close_thread:
    mov rcx,hRenderThread
    test rcx,rcx
    jz main_close_window
    mov edx,0FFFFFFFFh
    call WaitForSingleObject
    mov rcx,hRenderThread
    call CloseHandle
main_close_window:
    mov rcx,hWindow
    test rcx,rcx
    jz main_close_event
    call DestroyWindow
main_close_event:
    mov rcx,hStopEvent
    test rcx,rcx
    jz main_exit
    call CloseHandle
main_exit:
    xor ecx,ecx
    call ExitProcess
    add rsp,88h
    ret
main ENDP

WndProc PROC FRAME
    sub rsp,58h
    .allocstack 58h
    .endprolog
    mov [rsp+20h],rcx
    mov [rsp+28h],rdx
    mov [rsp+30h],r8
    mov [rsp+38h],r9
    cmp edx,0112h                    ; WM_SYSCOMMAND
    je wnd_system_command
    cmp edx,WM_CLOSE
    je wnd_close
    cmp edx,WM_RENDER_DONE
    je wnd_done
    cmp edx,WM_DESTROY
    je wnd_destroy
    cmp edx,WM_ERASEBKGND
    je wnd_erase
    cmp edx,WM_SIZE
    je wnd_size
    cmp edx,WM_KEYDOWN
    je wnd_keydown
    cmp edx,WM_KEYUP
    je wnd_keyup
    cmp edx,0201h ; WM_LBUTTONDOWN
    je wnd_focus
    cmp edx,WM_RBUTTONDOWN
    je wnd_down
    cmp edx,WM_RBUTTONUP
    je wnd_up
    cmp edx,WM_MOUSEMOVE
    je wnd_move
    cmp edx,WM_CAPTURECHANGED
    je wnd_capture
    cmp edx,WM_KILLFOCUS
    je wnd_blur
wnd_default:
    call DefWindowProcA
    jmp wnd_return
wnd_system_command:
    mov eax,r8d
    and eax,0FFF0h
    cmp eax,01E10h                   ; restore release
    je wnd_store_command
    cmp eax,01E20h                   ; fullscreen
    je wnd_store_command
    cmp eax,01E30h                   ; build information
    je wnd_store_command
    cmp eax,01E40h                   ; voluntary-donation mode
    jne wnd_default
wnd_store_command:
    xchg eax,windowCommand           ; UI producer, render-thread consumer
    jmp wnd_zero
wnd_size:
    movzx eax,r9w
    mov clientWidth,eax
    shr r9d,16
    mov clientHeight,r9d
    jmp wnd_zero
wnd_keydown:
    cmp r8d,255
    ja wnd_zero
    lea r10,keyState
    mov BYTE PTR [r10+r8],1
    cmp r8d,07Ah                     ; F11
    jne wnd_check_escape
    test r9d,40000000h               ; ignore auto-repeat
    jnz wnd_zero
    mov eax,01E20h
    jmp wnd_store_command
wnd_check_escape:
    cmp r8d,27
    jne wnd_check_reset
    test runtimeFlags,4
    jnz wnd_close
wnd_check_reset:
    cmp r8d,82
    jne wnd_key_bit
    test runtimeFlags,2
    jz wnd_key_bit
    mov resetRequest,1
    jmp wnd_zero
wnd_key_bit:
    call KeyMask
    lock or controlBits,eax
    jmp wnd_zero
wnd_keyup:
    cmp r8d,255
    ja wnd_zero
    lea r10,keyState
    mov BYTE PTR [r10+r8],0
    call KeyMask
    not eax
    lock and controlBits,eax
    jmp wnd_zero
wnd_focus:
    call SetFocus
    jmp wnd_zero
wnd_down:
    movsx eax,r9w
    mov oldMouseX,eax
    mov eax,r9d
    sar eax,16
    mov oldMouseY,eax
    mov dragging,1
    call SetFocus
    mov rcx,[rsp+20h]
    call SetCapture
    jmp wnd_zero
wnd_up:
    mov dragging,0
    call ReleaseCapture
    jmp wnd_zero
wnd_capture:
    mov dragging,0
    jmp wnd_zero
wnd_blur:
    lea r10,keyState
    xor ecx,ecx
wnd_clear_keys:
    mov BYTE PTR [r10+rcx],0
    inc ecx
    cmp ecx,256
    jb wnd_clear_keys
    xor eax,eax
    xchg eax,controlBits
    xor eax,eax
    xchg eax,mouseDX
    xor eax,eax
    xchg eax,mouseDY
    jmp wnd_up
wnd_move:
    cmp dragging,0
    je wnd_zero
    movsx eax,r9w
    mov edx,eax
    sub edx,oldMouseX
    mov oldMouseX,eax
    lock add mouseDX,edx
    mov eax,r9d
    sar eax,16
    mov edx,eax
    sub edx,oldMouseY
    mov oldMouseY,eax
    lock add mouseDY,edx
    jmp wnd_zero
wnd_close:
    ; Keep HWND/HDC alive until the render thread has released its GL context.
    mov rcx,hStopEvent
    call SetEvent
    jmp wnd_zero
wnd_done:
    mov rdx,renderError
    test rdx,rdx
    jz wnd_delete
    mov rcx,[rsp+20h]
    lea r8,className
    mov r9d,10h
    call MessageBoxA
wnd_delete:
    mov rcx,[rsp+20h]
    call DestroyWindow
    jmp wnd_zero
wnd_destroy:
    mov hWindow,0
    mov rcx,hStopEvent
    call SetEvent
    xor ecx,ecx
    call PostQuitMessage
    jmp wnd_zero
wnd_erase:
    mov eax,1
    jmp wnd_return
wnd_zero:
    xor eax,eax
wnd_return:
    add rsp,58h
    ret
WndProc ENDP

RenderThread PROC FRAME
    sub rsp,48h
    .allocstack 48h
    .endprolog
    lea rax,dcError
    mov renderError,rax
    mov rcx,hWindow
    call GetDC
    mov hDeviceContext,rax
    test rax,rax
    jz render_cleanup
    lea rax,pixelError
    mov renderError,rax
    mov WORD PTR pixelFormat[0],40
    mov WORD PTR pixelFormat[2],1
    mov DWORD PTR pixelFormat[4],25h  ; DOUBLEBUFFER | DRAW_TO_WINDOW | SUPPORT_OPENGL
    mov BYTE PTR pixelFormat[9],32
    mov BYTE PTR pixelFormat[23],24   ; depth buffer
    mov BYTE PTR pixelFormat[24],8    ; stencil buffer
    mov rcx,hDeviceContext
    lea rdx,pixelFormat
    call ChoosePixelFormat
    test eax,eax
    jz render_cleanup
    mov edx,eax
    mov rcx,hDeviceContext
    lea r8,pixelFormat
    call SetPixelFormat
    test eax,eax
    jz render_cleanup
    lea rax,contextError
    mov renderError,rax
    mov rcx,hDeviceContext
    call wglCreateContext
    mov hGLContext,rax
    test rax,rax
    jz render_cleanup
    mov rdx,rax
    mov rcx,hDeviceContext
    call wglMakeCurrent
    test eax,eax
    jz render_cleanup
    mov renderError,0
    xorps xmm0,xmm0
    xorps xmm1,xmm1
    xorps xmm2,xmm2
    movss xmm3,fOne
    call glClearColor                ; black background
    mov ecx,GL_DEPTH_TEST
    call glEnable
    call NativeInit
    call PythonStart
    test eax,eax
    jz render_python_error
    call GetTickCount64
    mov [rsp+30h],rax
render_loop:
    mov rcx,hStopEvent
    xor edx,edx
    call WaitForSingleObject
    test eax,eax
    jz render_cleanup
    call GetTickCount64
    mov rdx,rax
    sub rax,[rsp+30h]
    mov [rsp+30h],rdx
    cmp rax,50
    jbe render_dt_ok
    mov eax,50                      ; clamp long stalls to 50 ms of simulation
render_dt_ok:
    cvtsi2ss xmm0,rax
    mulss xmm0,fMillis
    movss frameDelta,xmm0
    call UpdateCamera
    call PythonFrame
    test eax,eax
    jz render_python_error
    call RenderSystem
    ; Sleep only the remaining frame budget. The stop event wakes us immediately.
    call GetTickCount64
    sub rax,[rsp+30h]
    xor edx,edx
    cmp rax,16
    jae render_wait
    mov edx,16
    sub edx,eax
render_wait:
    mov rcx,hStopEvent
    call WaitForSingleObject
    cmp eax,258                     ; WAIT_TIMEOUT
    je render_loop
    jmp render_cleanup
render_python_error:
    lea rax,pythonError
    mov renderError,rax
render_cleanup:
    cmp hGLContext,0
    je render_release_dc
    call PythonStop
    xor ecx,ecx
    xor edx,edx
    call wglMakeCurrent
    mov rcx,hGLContext
    call wglDeleteContext
    mov hGLContext,0
render_release_dc:
    mov rdx,hDeviceContext
    test rdx,rdx
    jz render_notify
    mov rcx,hWindow
    call ReleaseDC
    mov hDeviceContext,0
render_notify:
    mov rcx,hWindow
    mov edx,WM_RENDER_DONE
    xor r8d,r8d
    xor r9d,r9d
    call PostMessageA
    xor eax,eax
    add rsp,48h
    ret
RenderThread ENDP

RenderSystem PROC FRAME
    sub rsp,48h
    .allocstack 48h
    .endprolog
    mov eax,clientWidth
    mov edx,clientHeight
    test eax,eax
    jz frame_done
    test edx,edx
    jz frame_done
    mov [rsp+30h],eax                ; consistent width/height for this frame
    mov [rsp+34h],edx
    mov r8d,eax
    mov r9d,edx
    xor ecx,ecx
    xor edx,edx
    call glViewport
    mov ecx,4100h                    ; COLOR_BUFFER_BIT | DEPTH_BUFFER_BIT
    call glClear
    mov ecx,GL_PROJECTION
    call glMatrixMode
    call glLoadIdentity
    cvtsi2sd xmm1,DWORD PTR [rsp+30h]
    cvtsi2sd xmm4,DWORD PTR [rsp+34h]
    divsd xmm1,xmm4
    mulsd xmm1,dTop                  ; right = top * aspect
    xorpd xmm0,xmm0
    subsd xmm0,xmm1                  ; left = -right
    movsd xmm2,dBottom
    movsd xmm3,dTop
    mov rax,QWORD PTR dNear
    mov [rsp+20h],rax                ; argument 5: near (double)
    mov rax,QWORD PTR dFar
    mov [rsp+28h],rax                ; argument 6: far (double)
    call glFrustum
    mov ecx,GL_MODELVIEW
    call glMatrixMode
    call glLoadIdentity
    movss xmm0,cameraPitch
    movss xmm1,fOne
    xorps xmm2,xmm2
    xorps xmm3,xmm3
    call glRotatef
    movss xmm0,cameraYaw
    xorps xmm1,xmm1
    movss xmm2,fOne
    xorps xmm3,xmm3
    call glRotatef
    lea r10,cameraPosition
    xorps xmm0,xmm0
    xorps xmm1,xmm1
    xorps xmm2,xmm2
    subss xmm0,REAL4 PTR [r10]
    subss xmm1,REAL4 PTR [r10+4]
    subss xmm2,REAL4 PTR [r10+8]
    call glTranslatef
    call ApplyLight
    call NativeRender
    call PythonDraw
    test eax,eax
    jnz draw_python_ok
    lea rax,pythonError
    mov renderError,rax
    mov rcx,hStopEvent
    call SetEvent
 draw_python_ok:
    mov rcx,hDeviceContext
    call SwapBuffers
frame_done:
    add rsp,48h
    ret
RenderSystem ENDP

; Called only on the render thread. Atomic read-and-clear; no Python on the UI thread.
EnginePollWindowCommand PROC
    xor eax,eax
    xchg eax,windowCommand
    ret
EnginePollWindowCommand ENDP

; UI helper: R8D=virtual key -> EAX=mailbox mask. No calls, volatile regs only.
KeyMask PROC
    mov eax,1
    cmp r8d,'W'
    je km_done
    mov eax,2
    cmp r8d,'S'
    je km_done
    mov eax,4
    cmp r8d,'A'
    je km_done
    mov eax,8
    cmp r8d,'D'
    je km_done
    mov eax,16
    cmp r8d,32
    je km_done
    mov eax,32
    cmp r8d,17
    je km_done
    mov eax,64
    cmp r8d,16
    je km_done
    mov eax,128
    cmp r8d,37
    je km_done
    mov eax,256
    cmp r8d,39
    je km_done
    mov eax,512
    cmp r8d,38
    je km_done
    mov eax,1024
    cmp r8d,40
    je km_done
    xor eax,eax
km_done:
    ret
KeyMask ENDP
END
