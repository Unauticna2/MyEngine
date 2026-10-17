; Unauticna ASM map engine -- pure MASM x64 scene parsers.
; Win64 ABI. No CRT or OS calls. Only one loader thread may use this module.
; All reads are bounded by pEnd. EAX=1 success / EAX=0 failure.
option casemap:none
PUBLIC ParseMap, ParseObj, SameString
PUBLIC entityCount, modelPaths, positions, colors
PUBLIC triangleCount, triangles, parseOffset
MAX_ENTITIES EQU 1024
PATH_BYTES EQU 512
MAX_VERTICES EQU 65536
MAX_TRIANGLES EQU 131072
MAX_FACE EQU 256

.data
entityCount DWORD 0
triangleCount DWORD 0
parseOffset QWORD 0
pCur QWORD 0
pEnd QWORD 0
pBase QWORD 0
numberMode DWORD 0                 ; 0: JSON, 1: OBJ
vertexCount DWORD 0
modelCount DWORD 0
positionCount DWORD 0
colorCount DWORD 0
keyModel BYTE "model",0
keyPositions BYTE "positions",0
keyColors BYTE "colors",0
keyXYZ BYTE "xyz",0
keyRGB BYTE "rgb",0
fZero REAL4 0.0
fOne REAL4 1.0
fHalf REAL4 0.5
fAmbient REAL4 0.2
fDiffuse REAL4 0.8
fCoordMax REAL4 1000000.0
fCoordMin REAL4 -1000000.0
fEpsilon REAL4 1.0e-20
dTen REAL8 10.0

.data?
ALIGN 16
modelPaths BYTE MAX_ENTITIES * PATH_BYTES DUP(?)
positions REAL4 MAX_ENTITIES * 3 DUP(?)
colors REAL4 MAX_ENTITIES * 3 DUP(?)
vertices REAL4 MAX_VERTICES * 3 DUP(?)
; Each triangle: one brightness + three xyz vertices = 40 bytes.
triangles REAL4 MAX_TRIANGLES * 10 DUP(?)
faceIndices DWORD MAX_FACE DUP(?)
keyBuffer BYTE PATH_BYTES DUP(?)

.code
; Compare NUL-terminated strings: RCX, RDX. Volatile registers only.
SameString PROC
ss_loop:
    mov al,[rcx]
    cmp al,[rdx]
    jne ss_no
    inc rcx
    inc rdx
    test al,al
    jnz ss_loop
    mov eax,1
    ret
ss_no:
    xor eax,eax
    ret
SameString ENDP

SkipWhite PROC
    mov r10,pCur
sw_loop:
    cmp r10,pEnd
    jae sw_end
    movzx eax,BYTE PTR [r10]
    cmp al,32
    je sw_next
    cmp al,9
    je sw_next
    cmp al,10
    je sw_next
    cmp al,13
    jne sw_done
sw_next:
    inc r10
    jmp sw_loop
sw_end:
    xor eax,eax
sw_done:
    mov pCur,r10
    ret
SkipWhite ENDP

; EDX = expected ASCII punctuation.
Expect PROC FRAME
    sub rsp,28h
    .allocstack 28h
    .endprolog
    call SkipWhite
    cmp eax,edx
    jne ex_no
    cmp r10,pEnd
    jae ex_no
    inc pCur
    mov eax,1
    jmp ex_ret
ex_no:
    xor eax,eax
ex_ret:
    add rsp,28h
    ret
Expect ENDP

; Read exactly four hex digits at R10, bounded by pEnd. EAX=code or -1.
Hex4 PROC
    xor eax,eax
    mov r11d,4
hx_loop:
    cmp r10,pEnd
    jae hx_fail
    movzx edx,BYTE PTR [r10]
    inc r10
    sub edx,'0'
    cmp edx,9
    jbe hx_digit
    add edx,'0'
    or edx,32
    sub edx,'a'
    cmp edx,5
    ja hx_fail
    add edx,10
hx_digit:
    shl eax,4
    or eax,edx
    dec r11d
    jnz hx_loop
    ret
hx_fail:
    mov eax,-1
    ret
Hex4 ENDP

; RCX=destination, EDX=capacity including NUL. Decode JSON escapes to UTF-8.
ReadString PROC FRAME
    push rbx
    .pushreg rbx
    push rsi
    .pushreg rsi
    push rdi
    .pushreg rdi
    sub rsp,30h
    .allocstack 30h
    .endprolog
    mov rdi,rcx
    mov ebx,edx
    xor esi,esi
    call SkipWhite
    cmp al,34
    jne str_fail
    inc r10
str_loop:
    cmp r10,pEnd
    jae str_fail
    movzx eax,BYTE PTR [r10]
    inc r10
    cmp al,34
    je str_done
    cmp al,32
    jb str_fail
    cmp al,92
    jne str_put
    cmp r10,pEnd
    jae str_fail
    movzx eax,BYTE PTR [r10]
    inc r10
    cmp al,34
    je str_put
    cmp al,92
    je str_put
    cmp al,47
    je str_put
    cmp al,'u'
    je str_unicode
    cmp al,'b'
    je str_bs
    cmp al,'f'
    je str_ff
    cmp al,'n'
    je str_lf
    cmp al,'r'
    je str_cr
    cmp al,'t'
    jne str_fail
    mov eax,9
    jmp str_put
str_bs:
    mov eax,8
    jmp str_put
str_ff:
    mov eax,12
    jmp str_put
str_lf:
    mov eax,10
    jmp str_put
str_cr:
    mov eax,13
    jmp str_put
str_unicode:
    call Hex4
    cmp eax,-1
    je str_fail
    test eax,eax                     ; NUL is not a valid file/key character here
    jz str_fail
    cmp eax,0D800h
    jb str_encode
    cmp eax,0DFFFh
    ja str_encode
    cmp eax,0DBFFh
    ja str_fail                     ; reject lone low surrogate
    mov [rsp+20h],eax
    lea rax,[r10+2]
    cmp rax,pEnd
    ja str_fail
    cmp BYTE PTR [r10],92
    jne str_fail
    cmp BYTE PTR [r10+1],'u'
    jne str_fail
    add r10,2
    call Hex4
    cmp eax,0DC00h
    jb str_fail
    cmp eax,0DFFFh
    ja str_fail
    sub eax,0DC00h
    mov edx,[rsp+20h]
    sub edx,0D800h
    shl edx,10
    add eax,edx
    add eax,10000h
str_encode:
    lea edx,[rsi+4]
    cmp edx,ebx
    jae str_fail
    cmp eax,80h
    jb str_put
    mov edx,eax
    cmp eax,800h
    jb str_two
    cmp eax,10000h
    jb str_three
    shr eax,18
    or al,0F0h
    mov [rdi+rsi],al
    inc esi
    mov eax,edx
    shr eax,12
    and al,3Fh
    or al,80h
    mov [rdi+rsi],al
    inc esi
    jmp str_last_two
str_three:
    shr eax,12
    or al,0E0h
    mov [rdi+rsi],al
    inc esi
str_last_two:
    mov eax,edx
    shr eax,6
    and al,3Fh
    or al,80h
    mov [rdi+rsi],al
    inc esi
    jmp str_last
str_two:
    shr eax,6
    or al,0C0h
    mov [rdi+rsi],al
    inc esi
str_last:
    mov eax,edx
    and al,3Fh
    or al,80h
str_put:
    lea edx,[rsi+1]
    cmp edx,ebx
    jae str_fail
    mov [rdi+rsi],al
    inc esi
    jmp str_loop
str_done:
    mov BYTE PTR [rdi+rsi],0
    mov pCur,r10
    mov eax,1
    jmp str_ret
str_fail:
    mov pCur,r10
    xor eax,eax
str_ret:
    add rsp,30h
    pop rdi
    pop rsi
    pop rbx
    ret
ReadString ENDP

; Bounded decimal -> float. JSON grammar, or OBJ +1/.5/1. grammar.
; Reject NaN/Infinity and coordinates outside +/-1e6.
ReadNumber PROC FRAME
    sub rsp,28h
    .allocstack 28h
    .endprolog
    call SkipWhite
    xor r8d,r8d                      ; sign
    xor r9d,r9d                      ; digit count
    xorpd xmm0,xmm0
    cmp al,'-'
    jne num_plus
    mov r8d,1
    inc r10
    jmp num_int_start
num_plus:
    cmp al,'+'
    jne num_int_start
    cmp numberMode,0
    je num_fail
    inc r10
num_int_start:
    cmp r10,pEnd
    jae num_fail
    cmp numberMode,0
    jne num_int_loop
    cmp BYTE PTR [r10],'0'
    jne num_json_nonzero
    inc r10
    inc r9d
    cmp r10,pEnd
    jae num_fraction
    movzx eax,BYTE PTR [r10]
    sub eax,'0'
    cmp eax,9
    jbe num_fail                     ; no leading zero in JSON
    jmp num_fraction
num_json_nonzero:
    movzx eax,BYTE PTR [r10]
    sub eax,'1'
    cmp eax,8
    ja num_fail
num_int_loop:
    cmp r10,pEnd
    jae num_fraction
    movzx eax,BYTE PTR [r10]
    sub eax,'0'
    cmp eax,9
    ja num_fraction
    mulsd xmm0,dTen
    cvtsi2sd xmm1,eax
    addsd xmm0,xmm1
    inc r10
    inc r9d
    jmp num_int_loop
num_fraction:
    cmp r10,pEnd
    jae num_exponent
    cmp BYTE PTR [r10],'.'
    jne num_exponent
    inc r10
    movsd xmm2,dTen
    xor ecx,ecx
num_frac_loop:
    cmp r10,pEnd
    jae num_frac_end
    movzx eax,BYTE PTR [r10]
    sub eax,'0'
    cmp eax,9
    ja num_frac_end
    cvtsi2sd xmm1,eax
    divsd xmm1,xmm2
    addsd xmm0,xmm1
    mulsd xmm2,dTen
    inc ecx
    inc r9d
    inc r10
    jmp num_frac_loop
num_frac_end:
    test ecx,ecx
    jnz num_exponent
    cmp numberMode,0
    je num_fail
num_exponent:
    test r9d,r9d
    jz num_fail
    cmp r10,pEnd
    jae num_finish
    mov al,[r10]
    or al,32
    cmp al,'e'
    jne num_finish
    inc r10
    xor r9d,r9d                      ; exponent sign
    cmp r10,pEnd
    jae num_fail
    cmp BYTE PTR [r10],'-'
    jne num_exp_plus
    mov r9d,1
    inc r10
    jmp num_exp_start
num_exp_plus:
    cmp BYTE PTR [r10],'+'
    jne num_exp_start
    inc r10
num_exp_start:
    xor ecx,ecx
    xor edx,edx
num_exp_loop:
    cmp r10,pEnd
    jae num_exp_end
    movzx eax,BYTE PTR [r10]
    sub eax,'0'
    cmp eax,9
    ja num_exp_end
    imul ecx,ecx,10
    add ecx,eax
    cmp ecx,400
    ja num_fail
    inc edx
    inc r10
    jmp num_exp_loop
num_exp_end:
    test edx,edx
    jz num_fail
    test ecx,ecx
    jz num_finish
num_exp_apply:
    test r9d,r9d
    jnz num_exp_div
    mulsd xmm0,dTen
    jmp num_exp_next
num_exp_div:
    divsd xmm0,dTen
num_exp_next:
    dec ecx
    jnz num_exp_apply
num_finish:
    ; A number must end at a delimiter, never in an identifier or another number.
    cmp r10,pEnd
    jae num_sign
    mov al,[r10]
    cmp al,32
    je num_sign
    cmp al,9
    je num_sign
    cmp al,13
    je num_sign
    cmp al,10
    je num_sign
    cmp numberMode,0
    jne num_obj_delim
    cmp al,','
    je num_sign
    cmp al,']'
    je num_sign
    cmp al,'}'
    jne num_fail
    jmp num_sign
num_obj_delim:
    cmp al,'#'
    jne num_fail
num_sign:
    test r8d,r8d
    jz num_convert
    xorpd xmm1,xmm1
    subsd xmm1,xmm0
    movapd xmm0,xmm1
num_convert:
    cvtsd2ss xmm0,xmm0
    ucomiss xmm0,fCoordMax
    ja num_fail
    jp num_fail
    ucomiss xmm0,fCoordMin
    jb num_fail
    mov pCur,r10
    mov eax,1
    jmp num_ret
num_fail:
    mov pCur,r10
    xor eax,eax
num_ret:
    add rsp,28h
    ret
ReadNumber ENDP

; RCX=three-float destination, EDX=0 xyz or 1 rgb. Any key order.
ReadTriple PROC FRAME
    push rbx
    .pushreg rbx
    push rsi
    .pushreg rsi
    push rdi
    .pushreg rdi
    sub rsp,30h
    .allocstack 30h
    .endprolog
    mov rdi,rcx
    mov esi,edx
    xor ebx,ebx                      ; seen mask
    mov edx,'{'
    call Expect
    test eax,eax
    jz triple_fail
triple_loop:
    lea rcx,keyBuffer
    mov edx,PATH_BYTES
    call ReadString
    test eax,eax
    jz triple_fail
    lea r10,keyBuffer
    cmp BYTE PTR [r10+1],0
    jne triple_fail
    lea r10,keyXYZ
    test esi,esi
    jz triple_keys
    lea r10,keyRGB
triple_keys:
    xor ecx,ecx
    mov al,keyBuffer
triple_key_loop:
    cmp al,[r10+rcx]
    je triple_found
    inc ecx
    cmp ecx,3
    jb triple_key_loop
    jmp triple_fail
triple_found:
    mov [rsp+20h],ecx
    mov eax,1
    shl eax,cl
    test ebx,eax
    jnz triple_fail
    or ebx,eax
    mov edx,':'
    call Expect
    test eax,eax
    jz triple_fail
    call ReadNumber
    test eax,eax
    jz triple_fail
    test esi,esi
    jz triple_store
    ucomiss xmm0,fZero
    jb triple_fail
    ucomiss xmm0,fOne
    ja triple_fail
triple_store:
    mov ecx,[rsp+20h]
    movss REAL4 PTR [rdi+rcx*4],xmm0
    call SkipWhite
    cmp al,'}'
    je triple_done
    cmp al,','
    jne triple_fail
    inc pCur
    jmp triple_loop
triple_done:
    inc pCur
    cmp ebx,7
    jne triple_fail
    mov eax,1
    jmp triple_ret
triple_fail:
    xor eax,eax
triple_ret:
    add rsp,30h
    pop rdi
    pop rsi
    pop rbx
    ret
ReadTriple ENDP

; ECX=array kind 0 paths, 1 positions, 2 colors. Return count in EDX.
ReadArray PROC FRAME
    push rbx
    .pushreg rbx
    push rsi
    .pushreg rsi
    push rdi
    .pushreg rdi
    sub rsp,20h
    .allocstack 20h
    .endprolog
    mov esi,ecx
    xor ebx,ebx
    mov edx,'['
    call Expect
    test eax,eax
    jz array_fail
    call SkipWhite
    cmp al,']'
    je array_done
array_loop:
    cmp ebx,MAX_ENTITIES
    jae array_fail
    test esi,esi
    jnz array_vector
    mov eax,ebx
    shl eax,9
    lea rdi,modelPaths
    add rdi,rax
    mov rcx,rdi
    mov edx,PATH_BYTES
    call ReadString
    test eax,eax
    jz array_fail
    cmp BYTE PTR [rdi],0
    je array_fail
    jmp array_next
array_vector:
    lea rdi,positions
    cmp esi,1
    je array_dst
    lea rdi,colors
array_dst:
    imul eax,ebx,12
    lea rcx,[rdi+rax]
    lea edx,[rsi-1]
    call ReadTriple
    test eax,eax
    jz array_fail
array_next:
    inc ebx
    call SkipWhite
    cmp al,']'
    je array_done
    cmp al,','
    jne array_fail
    inc pCur
    jmp array_loop
array_done:
    inc pCur
    mov edx,ebx
    mov eax,1
    jmp array_ret
array_fail:
    xor eax,eax
array_ret:
    add rsp,20h
    pop rdi
    pop rsi
    pop rbx
    ret
ReadArray ENDP

; Map schema: exactly model[], positions[], colors[] with equal lengths.
ParseMap PROC FRAME
    push rbx
    .pushreg rbx
    push rsi
    .pushreg rsi
    push rdi
    .pushreg rdi
    sub rsp,20h
    .allocstack 20h
    .endprolog
    mov pBase,rcx
    mov pCur,rcx
    add rdx,rcx
    mov pEnd,rdx
    mov entityCount,0
    mov numberMode,0
    xor ebx,ebx
    ; Optional UTF-8 BOM.
    lea rax,[rcx+3]
    cmp rax,rdx
    ja map_open
    cmp BYTE PTR [rcx],0EFh
    jne map_open
    cmp WORD PTR [rcx+1],0BFBBh
    jne map_open
    add pCur,3
map_open:
    mov edx,'{'
    call Expect
    test eax,eax
    jz map_fail
map_loop:
    lea rcx,keyBuffer
    mov edx,PATH_BYTES
    call ReadString
    test eax,eax
    jz map_fail
    xor esi,esi
    lea rcx,keyBuffer
    lea rdx,keyModel
    call SameString
    test eax,eax
    jnz map_field
    inc esi
    lea rcx,keyBuffer
    lea rdx,keyPositions
    call SameString
    test eax,eax
    jnz map_field
    inc esi
    lea rcx,keyBuffer
    lea rdx,keyColors
    call SameString
    test eax,eax
    jz map_fail
map_field:
    mov ecx,esi
    mov eax,1
    shl eax,cl
    test ebx,eax
    jnz map_fail
    or ebx,eax
    mov edx,':'
    call Expect
    test eax,eax
    jz map_fail
    mov ecx,esi
    call ReadArray
    test eax,eax
    jz map_fail
    test esi,esi
    jnz map_not_model
    mov modelCount,edx
    jmp map_next
map_not_model:
    cmp esi,1
    jne map_color
    mov positionCount,edx
    jmp map_next
map_color:
    mov colorCount,edx
map_next:
    call SkipWhite
    cmp al,'}'
    je map_done
    cmp al,','
    jne map_fail
    inc pCur
    jmp map_loop
map_done:
    inc pCur
    call SkipWhite
    mov rax,pCur
    cmp rax,pEnd
    jne map_fail
    cmp ebx,7
    jne map_fail
    mov eax,modelCount
    cmp eax,positionCount
    jne map_fail
    cmp eax,colorCount
    jne map_fail
    mov entityCount,eax
    mov eax,1
    jmp map_ret
map_fail:
    xor eax,eax
map_ret:
    mov rdx,pCur
    sub rdx,pBase
    mov parseOffset,rdx
    add rsp,20h
    pop rdi
    pop rsi
    pop rbx
    ret
ParseMap ENDP

; Read a face vertex reference: v, v/vt, v//vn or v/vt/vn.
; Return EDX = resolved zero-based position index. vt/vn are syntactically checked
; but not used: this version computes a flat geometric normal for every triangle.
ReadIndex PROC FRAME
    sub rsp,28h
    .allocstack 28h
    .endprolog
    call SkipWhite
    xor r8d,r8d
    cmp al,'-'
    jne idx_digits
    inc r10
    mov r8d,1
idx_digits:
    xor ecx,ecx
    xor edx,edx
idx_loop:
    cmp r10,pEnd
    jae idx_resolve
    movzx eax,BYTE PTR [r10]
    sub eax,'0'
    cmp eax,9
    ja idx_resolve
    imul ecx,ecx,10
    add ecx,eax
    cmp ecx,MAX_VERTICES
    ja idx_fail
    inc r10
    inc edx
    jmp idx_loop
idx_resolve:
    test edx,edx
    jz idx_fail
    test ecx,ecx
    jz idx_fail
    test r8d,r8d
    jz idx_positive
    mov eax,vertexCount
    sub eax,ecx
    js idx_fail
    jmp idx_save
idx_positive:
    mov eax,ecx
    dec eax
    cmp eax,vertexCount
    jae idx_fail
idx_save:
    mov [rsp+20h],eax
    xor r8d,r8d                      ; slash count
idx_suffix:
    cmp r10,pEnd
    jae idx_done
    cmp BYTE PTR [r10],'/'
    jne idx_delim
    inc r8d
    cmp r8d,2
    ja idx_fail
    inc r10
    cmp r10,pEnd
    jae idx_fail
    cmp BYTE PTR [r10],'/'
    je idx_suffix                    ; empty vt allowed only before vn
    cmp BYTE PTR [r10],'-'
    jne idx_suffix_digits
    inc r10
idx_suffix_digits:
    xor ecx,ecx
idx_suffix_loop:
    cmp r10,pEnd
    jae idx_suffix_end
    movzx eax,BYTE PTR [r10]
    sub eax,'0'
    cmp eax,9
    ja idx_suffix_end
    inc ecx
    inc r10
    jmp idx_suffix_loop
idx_suffix_end:
    test ecx,ecx
    jz idx_fail
    jmp idx_suffix
idx_delim:
    mov al,[r10]
    cmp al,32
    je idx_done
    cmp al,9
    je idx_done
    cmp al,'#'
    jne idx_fail
idx_done:
    mov pCur,r10
    mov edx,[rsp+20h]
    mov eax,1
    jmp idx_ret
idx_fail:
    mov pCur,r10
    xor eax,eax
idx_ret:
    add rsp,28h
    ret
ReadIndex ENDP

; ECX/EDX/R8D position indices. Emit flat-shaded triangle, skip degenerates.
EmitTriangle PROC FRAME
    sub rsp,28h
    .allocstack 28h
    .endprolog
    imul ecx,ecx,12
    imul edx,edx,12
    imul r8d,r8d,12
    lea r10,vertices
    add rcx,r10
    add rdx,r10
    add r8,r10
    ; u = B-A, v = C-A. XMM3 stores normalized cross(u,v).y eventually.
    movss xmm0,REAL4 PTR [rdx]
    subss xmm0,REAL4 PTR [rcx]
    movss xmm1,REAL4 PTR [rdx+4]
    subss xmm1,REAL4 PTR [rcx+4]
    movss xmm2,REAL4 PTR [rdx+8]
    subss xmm2,REAL4 PTR [rcx+8]
    movss xmm3,REAL4 PTR [r8]
    subss xmm3,REAL4 PTR [rcx]
    movss xmm4,REAL4 PTR [r8+4]
    subss xmm4,REAL4 PTR [rcx+4]
    movss xmm5,REAL4 PTR [r8+8]
    subss xmm5,REAL4 PTR [rcx+8]
    ; Stack scratch (leaf; no shadow-space calls).
    movss REAL4 PTR [rsp],xmm0
    movss REAL4 PTR [rsp+4],xmm1
    movss REAL4 PTR [rsp+8],xmm2
    movss REAL4 PTR [rsp+12],xmm3
    movss REAL4 PTR [rsp+16],xmm4
    movss REAL4 PTR [rsp+20],xmm5
    mulss xmm1,xmm5
    mulss xmm2,xmm4
    subss xmm1,xmm2                  ; nx
    movss xmm2,REAL4 PTR [rsp+8]
    mulss xmm2,xmm3
    mulss xmm0,xmm5
    subss xmm2,xmm0                  ; ny
    movss xmm0,REAL4 PTR [rsp]
    mulss xmm0,xmm4
    movss xmm5,REAL4 PTR [rsp+4]
    mulss xmm5,xmm3
    subss xmm0,xmm5                  ; nz
    mulss xmm1,xmm1
    movaps xmm3,xmm2
    mulss xmm3,xmm3
    addss xmm1,xmm3
    mulss xmm0,xmm0
    addss xmm1,xmm0
    ucomiss xmm1,fEpsilon
    jbe tri_skip
    sqrtss xmm1,xmm1
    divss xmm2,xmm1
    addss xmm2,fOne
    mulss xmm2,fHalf
    mulss xmm2,fDiffuse
    addss xmm2,fAmbient              ; brightness = .2 + .8 * (ny+1)/2
    maxss xmm2,fAmbient
    minss xmm2,fOne
    mov eax,triangleCount
    cmp eax,MAX_TRIANGLES
    jae tri_full
    imul eax,eax,40
    lea r10,triangles
    add r10,rax
    movss REAL4 PTR [r10],xmm2
    mov rax,[rcx]
    mov [r10+4],rax
    mov eax,[rcx+8]
    mov [r10+12],eax
    mov rax,[rdx]
    mov [r10+16],rax
    mov eax,[rdx+8]
    mov [r10+24],eax
    mov rax,[r8]
    mov [r10+28],rax
    mov eax,[r8+8]
    mov [r10+36],eax
    inc triangleCount
tri_skip:
    mov eax,1
    add rsp,28h
    ret
tri_full:
    xor eax,eax
    add rsp,28h
    ret
EmitTriangle ENDP

; RCX=data, RDX=byte length. Supports triangles and convex polygons up to 256 sides.
ParseObj PROC FRAME
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
    mov pBase,rcx
    mov rsi,rcx
    lea rdi,[rcx+rdx]
    mov triangleCount,0
    mov vertexCount,0
    mov numberMode,1
    lea rax,[rsi+3]
    cmp rax,rdi
    ja obj_line
    cmp BYTE PTR [rsi],0EFh
    jne obj_line
    cmp WORD PTR [rsi+1],0BFBBh
    jne obj_line
    add rsi,3
obj_line:
    cmp rsi,rdi
    jae obj_done
    mov pCur,rsi
    mov r12,rsi
obj_find_end:
    cmp r12,rdi
    jae obj_line_end
    cmp BYTE PTR [r12],10
    je obj_line_end
    cmp BYTE PTR [r12],13
    je obj_line_end
    inc r12
    jmp obj_find_end
obj_line_end:
    mov pEnd,r12
    mov rsi,r12
    cmp rsi,rdi
    jae obj_read
    inc rsi                         ; CRLF becomes one extra empty line, harmless
obj_read:
    call SkipWhite
    cmp r10,r12
    jae obj_line
    cmp al,'v'
    je obj_vertex_check
    cmp al,'f'
    je obj_face_check
    jmp obj_line                     ; comments, vn/vt/o/g/s/mtllib/usemtl ignored
obj_vertex_check:
    inc r10
    cmp r10,r12
    jae obj_fail
    mov al,[r10]
    cmp al,32
    je obj_vertex
    cmp al,9
    jne obj_line                    ; vn, vt etc.
obj_vertex:
    mov pCur,r10
    mov eax,vertexCount
    cmp eax,MAX_VERTICES
    jae obj_fail
    imul eax,eax,12
    lea r13,vertices
    add r13,rax
    xor ebx,ebx
obj_vertex_number:
    call ReadNumber
    test eax,eax
    jz obj_fail
    movss REAL4 PTR [r13+rbx*4],xmm0
    inc ebx
    cmp ebx,3
    jb obj_vertex_number
    inc vertexCount
    jmp obj_line                     ; optional w / vertex RGB ignored
obj_face_check:
    inc r10
    cmp r10,r12
    jae obj_fail
    mov al,[r10]
    cmp al,32
    je obj_face
    cmp al,9
    jne obj_line
obj_face:
    mov pCur,r10
    xor ebx,ebx
    lea r13,faceIndices
obj_face_index:
    call SkipWhite
    cmp r10,r12
    jae obj_face_finish
    cmp al,'#'
    je obj_face_finish
    cmp ebx,MAX_FACE
    jae obj_fail
    call ReadIndex
    test eax,eax
    jz obj_fail
    mov [r13+rbx*4],edx
    inc ebx
    jmp obj_face_index
obj_face_finish:
    cmp ebx,3
    jb obj_fail
    mov DWORD PTR [rsp+20h],1
    dec ebx
obj_triangle:
    mov eax,[rsp+20h]
    mov ecx,[r13]
    mov edx,[r13+rax*4]
    mov r8d,[r13+rax*4+4]
    call EmitTriangle
    test eax,eax
    jz obj_fail
    inc DWORD PTR [rsp+20h]
    cmp DWORD PTR [rsp+20h],ebx
    jb obj_triangle
    jmp obj_line
obj_done:
    cmp triangleCount,0
    je obj_fail
    mov eax,1
    jmp obj_ret
obj_fail:
    xor eax,eax
obj_ret:
    mov rdx,pCur
    sub rdx,pBase
    mov parseOffset,rdx
    add rsp,30h
    pop r13
    pop r12
    pop rdi
    pop rsi
    pop rbx
    ret
ParseObj ENDP
END
