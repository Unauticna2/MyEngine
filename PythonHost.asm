; Embed a normal 64-bit CPython 3.11-3.13 installation in the render thread.
; setup_python.cmd writes absolute home/DLL paths to python.ini (UTF-16).
option casemap:none
EXTERN GetModuleFileNameW:PROC, SetCurrentDirectoryW:PROC
EXTERN GetFileAttributesW:PROC, GetFullPathNameW:PROC
EXTERN GetPrivateProfileStringW:PROC, LoadLibraryExW:PROC, GetProcAddress:PROC
PUBLIC PythonStart, PythonFrame, PythonStop, PythonDraw, EnginePortableV1
.data
pyModule QWORD 0
pyThreadState QWORD 0
pyStarted DWORD 0
pPy_SetPythonHome QWORD 0
nPy_SetPythonHome LABEL BYTE
    BYTE 80,121,95,83,101,116,80,121,116,104,111,110,72,111,109,101
    BYTE 0
pPy_InitializeEx QWORD 0
nPy_InitializeEx LABEL BYTE
    BYTE 80,121,95,73,110,105,116,105,97,108,105,122,101,69,120,0
pPyRun_SimpleString QWORD 0
nPyRun_SimpleString LABEL BYTE
    BYTE 80,121,82,117,110,95,83,105,109,112,108,101,83,116,114,105
    BYTE 110,103,0
pPyEval_SaveThread QWORD 0
nPyEval_SaveThread LABEL BYTE
    BYTE 80,121,69,118,97,108,95,83,97,118,101,84,104,114,101,97
    BYTE 100,0
pPyEval_RestoreThread QWORD 0
nPyEval_RestoreThread LABEL BYTE
    BYTE 80,121,69,118,97,108,95,82,101,115,116,111,114,101,84,104
    BYTE 114,101,97,100,0
pPy_FinalizeEx QWORD 0
nPy_FinalizeEx LABEL BYTE
    BYTE 80,121,95,70,105,110,97,108,105,122,101,69,120,0
section LABEL WORD
    WORD 80,121,116,104,111,110,0
homeKey LABEL WORD
    WORD 72,111,109,101,0
dllKey LABEL WORD
    WORD 68,76,76,0
iniName LABEL WORD
    WORD 46,92,112,121,116,104,111,110,46,105,110,105,0
dataIni WORD 46,92,68,97,116,97,92,112,121,116,104,111,110,46,105,110,105,0
dataDir WORD 46,92,68,97,116,97,0
empty LABEL WORD
    WORD 0
bootstrap LABEL BYTE
    BYTE 105,109,112,111,114,116,32,115,121,115,44,32,111,115,44,32,112,97,116,104
    BYTE 108,105,98,44,32,116,101,109,112,102,105,108,101,10,115,121,115,46,112,97
    BYTE 116,104,46,105,110,115,101,114,116,40,48,44,32,111,115,46,103,101,116,99
    BYTE 119,100,40,41,41,10,115,121,115,46,100,111,110,116,95,119,114,105,116,101
    BYTE 95,98,121,116,101,99,111,100,101,32,61,32,84,114,117,101,10,95,108,111
    BYTE 103,100,105,114,32,61,32,112,97,116,104,108,105,98,46,80,97,116,104,40
    BYTE 111,115,46,101,110,118,105,114,111,110,46,103,101,116,40,39,77,89,69,78
    BYTE 71,73,78,69,95,76,79,71,95,68,73,82,39,41,32,111,114,32,40,112
    BYTE 97,116,104,108,105,98,46,80,97,116,104,40,111,115,46,101,110,118,105,114
    BYTE 111,110,46,103,101,116,40,39,76,79,67,65,76,65,80,80,68,65,84,65
    BYTE 39,44,32,116,101,109,112,102,105,108,101,46,103,101,116,116,101,109,112,100
    BYTE 105,114,40,41,41,41,32,47,32,39,77,121,69,110,103,105,110,101,50,39
    BYTE 32,47,32,112,97,116,104,108,105,98,46,80,97,116,104,40,115,121,115,46
    BYTE 101,120,101,99,117,116,97,98,108,101,41,46,115,116,101,109,41,41,10,95
    BYTE 108,111,103,100,105,114,46,109,107,100,105,114,40,112,97,114,101,110,116,115
    BYTE 61,84,114,117,101,44,32,101,120,105,115,116,95,111,107,61,84,114,117,101
    BYTE 41,10,95,108,111,103,32,61,32,111,112,101,110,40,95,108,111,103,100,105
    BYTE 114,32,47,32,39,101,110,103,105,110,101,46,108,111,103,39,44,32,39,119
    BYTE 39,44,32,101,110,99,111,100,105,110,103,61,39,117,116,102,45,56,39,44
    BYTE 32,98,117,102,102,101,114,105,110,103,61,49,41,10,115,121,115,46,115,116
    BYTE 100,111,117,116,32,61,32,115,121,115,46,115,116,100,101,114,114,32,61,32
    BYTE 95,108,111,103,10,112,114,105,110,116,40,39,69,110,103,105,110,101,32,114
    BYTE 111,111,116,58,39,44,32,111,115,46,103,101,116,99,119,100,40,41,41,10
    BYTE 105,109,112,111,114,116,32,101,110,103,105,110,101,95,114,117,110,116,105,109
    BYTE 101,32,97,115,32,95,101,110,103,105,110,101,10,95,101,110,103,105,110,101
    BYTE 46,115,116,97,114,116,40,41,10,0
frameCode LABEL BYTE
    BYTE 95,101,110,103,105,110,101,46,102,114,97,109,101,40,41,10
    BYTE 0
drawCode BYTE "_engine.draw()",10,0
stopCode LABEL BYTE
    BYTE 105,102,32,39,95,101,110,103,105,110,101,39,32,105,110,32
    BYTE 103,108,111,98,97,108,115,40,41,58,32,95,101,110,103,105
    BYTE 110,101,46,115,104,117,116,100,111,119,110,40,41,10,0
.data?
appPath WORD 4096 DUP(?)
pythonHome WORD 4096 DUP(?)
pythonDLL WORD 4096 DUP(?)
fullHome WORD 4096 DUP(?)
fullDLL WORD 4096 DUP(?)
.code
EnginePortableV1 PROC
    mov eax,1
    ret
EnginePortableV1 ENDP
PythonStart PROC FRAME
    sub rsp,48h
    .allocstack 48h
    .endprolog
    xor ecx,ecx
    lea rdx,appPath
    mov r8d,4096
    call GetModuleFileNameW
    test eax,eax
    jz py_start_fail
    cmp eax,4096
    jae py_start_fail
    lea r10,appPath
py_dir:
    test eax,eax
    jz py_start_fail
    dec eax
    cmp WORD PTR [r10+rax*2],92
    jne py_dir
    mov WORD PTR [r10+rax*2],0
    mov rcx,r10
    call SetCurrentDirectoryW
    test eax,eax
    jz py_start_fail
    lea rcx,dataIni
    call GetFileAttributesW
    cmp eax,-1
    je py_regular_layout
    lea rcx,dataDir
    call SetCurrentDirectoryW
    test eax,eax
    jz py_start_fail
py_regular_layout:
    lea rcx,section
    lea rdx,homeKey
    lea r8,empty
    lea r9,pythonHome
    mov QWORD PTR [rsp+20h],4096
    lea rax,iniName
    mov [rsp+28h],rax
    call GetPrivateProfileStringW
    test eax,eax
    jz py_start_fail
    cmp eax,4095
    jae py_start_fail
    lea rcx,section
    lea rdx,dllKey
    lea r8,empty
    lea r9,pythonDLL
    mov QWORD PTR [rsp+20h],4096
    lea rax,iniName
    mov [rsp+28h],rax
    call GetPrivateProfileStringW
    test eax,eax
    jz py_start_fail
    cmp eax,4095
    jae py_start_fail
    lea rcx,pythonHome
    mov edx,4096
    lea r8,fullHome
    xor r9d,r9d
    call GetFullPathNameW
    test eax,eax
    jz py_start_fail
    cmp eax,4096
    jae py_start_fail
    lea rcx,pythonDLL
    mov edx,4096
    lea r8,fullDLL
    xor r9d,r9d
    call GetFullPathNameW
    test eax,eax
    jz py_start_fail
    cmp eax,4096
    jae py_start_fail
    lea rcx,fullDLL
    xor edx,edx
    mov r8d,8                        ; LOAD_WITH_ALTERED_SEARCH_PATH
    call LoadLibraryExW
    mov pyModule,rax
    test rax,rax
    jz py_start_fail
    mov rcx,pyModule
    lea rdx,nPy_SetPythonHome
    call GetProcAddress
    mov pPy_SetPythonHome,rax
    test rax,rax
    jz py_start_fail
    mov rcx,pyModule
    lea rdx,nPy_InitializeEx
    call GetProcAddress
    mov pPy_InitializeEx,rax
    test rax,rax
    jz py_start_fail
    mov rcx,pyModule
    lea rdx,nPyRun_SimpleString
    call GetProcAddress
    mov pPyRun_SimpleString,rax
    test rax,rax
    jz py_start_fail
    mov rcx,pyModule
    lea rdx,nPyEval_SaveThread
    call GetProcAddress
    mov pPyEval_SaveThread,rax
    test rax,rax
    jz py_start_fail
    mov rcx,pyModule
    lea rdx,nPyEval_RestoreThread
    call GetProcAddress
    mov pPyEval_RestoreThread,rax
    test rax,rax
    jz py_start_fail
    mov rcx,pyModule
    lea rdx,nPy_FinalizeEx
    call GetProcAddress
    mov pPy_FinalizeEx,rax
    test rax,rax
    jz py_start_fail
    lea rcx,fullHome
    call pPy_SetPythonHome
    xor ecx,ecx                      ; no signal handlers on this worker thread
    call pPy_InitializeEx
    mov pyStarted,1
    lea rcx,bootstrap
    call pPyRun_SimpleString
    test eax,eax
    jnz py_start_fail
    call pPyEval_SaveThread          ; let Python background threads run between frames
    mov pyThreadState,rax
    mov eax,1
    jmp py_start_ret
py_start_fail:
    xor eax,eax
py_start_ret:
    add rsp,48h
    ret
PythonStart ENDP
PythonFrame PROC FRAME
    sub rsp,38h
    .allocstack 38h
    .endprolog
    mov rcx,pyThreadState
    test rcx,rcx
    jz py_frame_fail
    call pPyEval_RestoreThread
    lea rcx,frameCode
    call pPyRun_SimpleString
    mov [rsp+20h],eax
    call pPyEval_SaveThread
    mov pyThreadState,rax
    cmp DWORD PTR [rsp+20h],0
    sete al
    movzx eax,al
    jmp py_frame_ret
py_frame_fail:
    xor eax,eax
py_frame_ret:
    add rsp,38h
    ret
PythonFrame ENDP
PythonDraw PROC FRAME
    sub rsp,38h
    .allocstack 38h
    .endprolog
    mov rcx,pyThreadState
    test rcx,rcx
    jz py_draw_fail
    call pPyEval_RestoreThread
    lea rcx,drawCode
    call pPyRun_SimpleString
    mov [rsp+20h],eax
    call pPyEval_SaveThread
    mov pyThreadState,rax
    cmp DWORD PTR [rsp+20h],0
    sete al
    movzx eax,al
    jmp py_draw_ret
py_draw_fail:
    xor eax,eax
py_draw_ret:
    add rsp,38h
    ret
PythonDraw ENDP
PythonStop PROC FRAME
    sub rsp,28h
    .allocstack 28h
    .endprolog
    cmp pyStarted,0
    je py_stop_ret
    mov rcx,pyThreadState
    test rcx,rcx
    jz py_stop_owned
    call pPyEval_RestoreThread
    mov pyThreadState,0
py_stop_owned:
    lea rcx,stopCode
    call pPyRun_SimpleString
    call pPy_FinalizeEx
    mov pyStarted,0
py_stop_ret:
    add rsp,28h
    ret
PythonStop ENDP
END
