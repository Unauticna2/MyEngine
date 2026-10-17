; Win32 file I/O + immutable mesh resource cache. MASM x64, no CRT.
option casemap:none
EXTERN GetModuleFileNameW:PROC, MultiByteToWideChar:PROC
EXTERN CreateFileW:PROC, GetFileSizeEx:PROC, ReadFile:PROC, CloseHandle:PROC
EXTERN VirtualAlloc:PROC, VirtualFree:PROC, GetLastError:PROC
EXTERN wsprintfW:PROC, WaitForSingleObject:PROC
EXTERN glGenLists:PROC, glNewList:PROC, glEndList:PROC, glDeleteLists:PROC
EXTERN glBegin:PROC, glEnd:PROC, glColor3f:PROC, glVertex3f:PROC, glGetError:PROC
EXTERN ParseMap:PROC, ParseObj:PROC, SameString:PROC
EXTERN entityCount:DWORD, modelPaths:BYTE, colors:REAL4
EXTERN triangleCount:DWORD, triangles:REAL4, parseOffset:QWORD
EXTERN hStopEvent:QWORD
PUBLIC LoadScene, DestroyScene, meshIds, sceneError
MAX_ENTITIES EQU 1024
MAX_PATH_CHARS EQU 2048
MAX_FILE_BYTES EQU 33554432

.data
rootChars DWORD 0
fileBytes DWORD 0
fileBuffer QWORD 0
fileError DWORD 0
mapName BYTE "map.json",0
; UTF-16 format strings for Unicode paths. wsprintfW limit is 1024 characters.
; Short initializers also fit Microsoft ml64 statement complexity limits.
readErrorFmt LABEL WORD
    WORD 'C','a','n','n','o','t',' ','r','e','a','d',' ','f','i','l','e'
    WORD ':',10,'%','s',10,10,'W','i','n','d','o','w','s',' ','e','r'
    WORD 'r','o','r',':',' ','%','u',0
mapErrorFmt LABEL WORD
    WORD 'I','n','v','a','l','i','d',' ','m','a','p','.','j','s','o','n'
    WORD ':',10,'%','s',10,10,'B','y','t','e',' ','o','f','f','s','e'
    WORD 't',':',' ','%','u',10,'C','h','e','c','k',' ','t','h','e',' '
    WORD 's','c','h','e','m','a',' ','a','n','d',' ','a','r','r','a','y'
    WORD ' ','l','e','n','g','t','h','s','.',0
objErrorFmt LABEL WORD
    WORD 'I','n','v','a','l','i','d',' ','o','r',' ','e','m','p','t','y'
    WORD ' ','O','B','J',':',10,'%','s',10,10,'B','y','t','e',' ','o'
    WORD 'f','f','s','e','t',':',' ','%','u',10,'C','h','e','c','k',' '
    WORD 'i','n','d','i','c','e','s',' ','a','n','d',' ','l','i','m','i'
    WORD 't','s','.',0
glErrorFmt LABEL WORD
    WORD 'O','p','e','n','G','L',' ','m','e','s','h',' ','e','r','r','o'
    WORD 'r',':',10,'%','s',10,10,'C','o','d','e',':',' ','%','u',0
pathErrorFmt LABEL WORD
    WORD 'I','n','v','a','l','i','d',' ','o','r',' ','t','o','o',' ','l'
    WORD 'o','n','g',' ','U','T','F','-','8',' ','p','a','t','h','.',0

.data?
ALIGN 8
basePath WORD MAX_PATH_CHARS DUP(?)
fullPath WORD MAX_PATH_CHARS DUP(?)
sceneError WORD 1024 DUP(?)
meshIds DWORD MAX_ENTITIES DUP(?)

.code
; Resolve map-relative UTF-8 path against the executable directory, not CWD.
; RCX=UTF-8 path. EAX=success. JSON map itself lives next to the EXE.
ResolvePath PROC FRAME
    sub rsp,48h
    .allocstack 48h
    .endprolog
    mov r8,rcx
    lea r10,basePath
    lea r11,fullPath
    xor eax,eax
    mov ecx,rootChars
rp_copy:
    cmp eax,ecx
    jae rp_convert
    mov dx,[r10+rax*2]
    mov [r11+rax*2],dx
    inc eax
    jmp rp_copy
rp_convert:
    lea rax,[r11+rcx*2]
    mov [rsp+20h],rax
    mov eax,MAX_PATH_CHARS
    sub eax,ecx
    mov [rsp+28h],eax
    mov ecx,65001                    ; CP_UTF8
    mov edx,8                        ; MB_ERR_INVALID_CHARS
    mov r9d,-1
    call MultiByteToWideChar
    test eax,eax
    setnz al
    movzx eax,al
    add rsp,48h
    ret
ResolvePath ENDP

; fileBuffer/fileBytes, 32 MiB maximum. Read all bytes, then append sentinel NUL.
; A sentinel is convenient but the parser does not depend on it.
LoadFile PROC FRAME
    push rbx
    .pushreg rbx
    push rsi
    .pushreg rsi
    push rdi
    .pushreg rdi
    sub rsp,60h
    .allocstack 60h
    .endprolog
    mov fileBuffer,0
    mov fileBytes,0
    mov fileError,0
    lea rcx,fullPath
    mov edx,80000000h                ; GENERIC_READ
    mov r8d,1                        ; FILE_SHARE_READ (no writes during loading)
    xor r9d,r9d
    mov QWORD PTR [rsp+20h],3         ; OPEN_EXISTING
    mov QWORD PTR [rsp+28h],80h       ; FILE_ATTRIBUTE_NORMAL
    mov QWORD PTR [rsp+30h],0
    call CreateFileW
    cmp rax,-1
    je lf_open_fail
    mov rbx,rax
    mov rcx,rbx
    lea rdx,[rsp+40h]
    call GetFileSizeEx
    test eax,eax
    jz lf_api_fail
    mov rax,[rsp+40h]
    cmp rax,MAX_FILE_BYTES
    ja lf_size_fail
    test rax,rax
    jz lf_size_fail
    mov fileBytes,eax
    lea rdx,[rax+1]
    xor ecx,ecx
    mov r8d,3000h                    ; MEM_RESERVE | MEM_COMMIT
    mov r9d,4                        ; PAGE_READWRITE
    call VirtualAlloc
    test rax,rax
    jz lf_api_fail
    mov fileBuffer,rax
    mov rsi,rax
    xor edi,edi
lf_read:
    mov rcx,rbx
    lea rdx,[rsi+rdi]
    mov r8d,fileBytes
    sub r8d,edi
    lea r9,[rsp+48h]
    mov QWORD PTR [rsp+20h],0
    call ReadFile
    test eax,eax
    jz lf_api_fail
    mov eax,[rsp+48h]
    test eax,eax
    jz lf_size_fail
    add edi,eax
    cmp edi,fileBytes
    jb lf_read
    mov BYTE PTR [rsi+rdi],0
    mov rcx,rbx
    call CloseHandle
    mov eax,1
    jmp lf_ret
lf_size_fail:
    mov fileError,13                ; ERROR_INVALID_DATA / size limit
    jmp lf_close
lf_api_fail:
    call GetLastError
    mov fileError,eax
lf_close:
    mov rcx,rbx
    call CloseHandle
    call FreeFile
    xor eax,eax
    jmp lf_ret
lf_open_fail:
    call GetLastError
    mov fileError,eax
    xor eax,eax
lf_ret:
    add rsp,60h
    pop rdi
    pop rsi
    pop rbx
    ret
LoadFile ENDP

FreeFile PROC FRAME
    sub rsp,28h
    .allocstack 28h
    .endprolog
    mov rcx,fileBuffer
    test rcx,rcx
    jz ff_ret
    xor edx,edx
    mov r8d,8000h                    ; MEM_RELEASE
    call VirtualFree
    mov fileBuffer,0
ff_ret:
    add rsp,28h
    ret
FreeFile ENDP

; RDX=format, R9D=code/offset. Keep only first 600 UTF-16 path chars in error.
SceneFailure PROC FRAME
    sub rsp,28h
    .allocstack 28h
    .endprolog
    lea r8,fullPath
    mov WORD PTR [r8+1200],0
    lea rcx,sceneError
    call wsprintfW
    xor eax,eax
    add rsp,28h
    ret
SceneFailure ENDP

LoadScene PROC FRAME
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
    sub rsp,30h
    .allocstack 30h
    .endprolog
    mov WORD PTR sceneError,0
    lea rdx,basePath
    xor ecx,ecx
    mov r8d,MAX_PATH_CHARS
    call GetModuleFileNameW
    test eax,eax
    jz ls_path_error
    cmp eax,MAX_PATH_CHARS
    jae ls_path_error
    lea r10,basePath
ls_find_slash:
    test eax,eax
    jz ls_path_error
    dec eax
    cmp WORD PTR [r10+rax*2],92
    jne ls_find_slash
    inc eax
    mov rootChars,eax
    lea rcx,mapName
    call ResolvePath
    test eax,eax
    jz ls_path_error
    call LoadFile
    test eax,eax
    jz ls_read_error
    mov rcx,fileBuffer
    mov edx,fileBytes
    call ParseMap
    mov ebx,eax
    call FreeFile
    test ebx,ebx
    jz ls_map_error
    xor ebx,ebx
    lea r12,meshIds
ls_entity:
    cmp ebx,entityCount
    jae ls_success
    mov rcx,hStopEvent
    xor edx,edx
    call WaitForSingleObject
    test eax,eax
    jz ls_cancel
    mov esi,ebx
    shl esi,9
    lea rdi,modelPaths
    add rdi,rsi
    imul esi,ebx,12
    lea r13,colors
    add r13,rsi
    xor esi,esi
    ; Reuse a display list for identical (path, RGB), regardless of position.
ls_cache:
    cmp esi,ebx
    jae ls_new_mesh
    mov eax,esi
    shl eax,9
    lea rdx,modelPaths
    add rdx,rax
    mov rcx,rdi
    call SameString
    test eax,eax
    jz ls_cache_next
    imul eax,esi,12
    lea rdx,colors
    add rdx,rax
    mov rax,[rdx]
    cmp rax,[r13]
    jne ls_cache_next
    mov eax,[rdx+8]
    cmp eax,[r13+8]
    jne ls_cache_next
    mov eax,[r12+rsi*4]
    mov [r12+rbx*4],eax
    jmp ls_next
ls_cache_next:
    inc esi
    jmp ls_cache
ls_new_mesh:
    mov rcx,rdi
    call ResolvePath
    test eax,eax
    jz ls_path_error
    call LoadFile
    test eax,eax
    jz ls_read_error
    mov rcx,fileBuffer
    mov edx,fileBytes
    call ParseObj
    mov esi,eax
    call FreeFile
    test esi,esi
    jz ls_obj_error
    ; Compile once at load time. The frame loop only calls cached lists.
    mov ecx,1
    call glGenLists
    test eax,eax
    jz ls_gl_error
    mov [r12+rbx*4],eax
    mov ecx,eax
    mov edx,1300h                    ; GL_COMPILE
    call glNewList
    mov ecx,4                        ; GL_TRIANGLES
    call glBegin
    lea rdi,triangles
    xor esi,esi
ls_triangle:
    cmp esi,triangleCount
    jae ls_mesh_end
    movss xmm3,REAL4 PTR [rdi]
    movss xmm0,REAL4 PTR [r13]
    movss xmm1,REAL4 PTR [r13+4]
    movss xmm2,REAL4 PTR [r13+8]
    mulss xmm0,xmm3
    mulss xmm1,xmm3
    mulss xmm2,xmm3
    call glColor3f
    mov DWORD PTR [rsp+20h],0
ls_vertex:
    mov eax,[rsp+20h]
    imul eax,eax,12
    movss xmm0,REAL4 PTR [rdi+rax+4]
    movss xmm1,REAL4 PTR [rdi+rax+8]
    movss xmm2,REAL4 PTR [rdi+rax+12]
    call glVertex3f
    inc DWORD PTR [rsp+20h]
    cmp DWORD PTR [rsp+20h],3
    jb ls_vertex
    add rdi,40
    inc esi
    jmp ls_triangle
ls_mesh_end:
    call glEnd
    call glEndList
    call glGetError
    test eax,eax
    jnz ls_gl_code
ls_next:
    inc ebx
    jmp ls_entity
ls_success:
    mov eax,1
    jmp ls_ret
ls_read_error:
    lea rdx,readErrorFmt
    mov r9d,fileError
    jmp ls_error
ls_map_error:
    lea rdx,mapErrorFmt
    mov r9d,DWORD PTR parseOffset
    jmp ls_error
ls_obj_error:
    lea rdx,objErrorFmt
    mov r9d,DWORD PTR parseOffset
    jmp ls_error
ls_path_error:
    lea rdx,pathErrorFmt
    xor r9d,r9d
    jmp ls_error
ls_gl_error:
    call glGetError
ls_gl_code:
    mov r9d,eax
    lea rdx,glErrorFmt
ls_error:
    call SceneFailure
    jmp ls_ret
ls_cancel:
    xor eax,eax
ls_ret:
    add rsp,30h
    pop r13
    pop r12
    pop rdi
    pop rsi
    pop rbx
    ret
LoadScene ENDP

; Called while this thread still owns the GL context. Delete every resource once.
DestroyScene PROC FRAME
    push rbx
    .pushreg rbx
    push rsi
    .pushreg rsi
    push rdi
    .pushreg rdi
    sub rsp,20h
    .allocstack 20h
    .endprolog
    lea rdi,meshIds
    xor ebx,ebx
 ds_loop:
    cmp ebx,entityCount
    jae ds_done
    mov esi,[rdi+rbx*4]
    test esi,esi
    jz ds_next
    mov ecx,esi
    mov edx,1
    call glDeleteLists
    mov eax,ebx
 ds_clear:
    cmp eax,entityCount
    jae ds_next
    cmp [rdi+rax*4],esi
    jne ds_clear_next
    mov DWORD PTR [rdi+rax*4],0
 ds_clear_next:
    inc eax
    jmp ds_clear
 ds_next:
    inc ebx
    jmp ds_loop
 ds_done:
    call FreeFile
    add rsp,20h
    pop rdi
    pop rsi
    pop rbx
    ret
DestroyScene ENDP
END
