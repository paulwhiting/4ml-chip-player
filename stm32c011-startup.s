.syntax unified
.cpu cortex-m0plus
.thumb

.global Reset_Handler
.global Default_Handler
.global SysTick_Handler

.section .isr_vector,"a",%progbits
.align 2

.word 0x20001800          /* Initial SP: 6 KB RAM */
.word Reset_Handler
.word Default_Handler     /* NMI */
.word Default_Handler     /* HardFault */
.word 0
.word 0
.word 0
.word 0
.word 0
.word 0
.word 0
.word Default_Handler     /* SVC */
.word 0
.word 0
.word Default_Handler     /* PendSV */
.word Default_Handler     /* SysTick */


/* ---------- Reset ---------- */

.section .text.Reset_Handler
.thumb_func

Reset_Handler:

    /*
     * Nothing to initialize:
     *
     * - code has no initialized globals
     * - no C library
     * - no .data section
     */

    bl main

1:
    b 1b


/* ---------- Default handler ---------- */

.section .text.Default_Handler
.thumb_func

Default_Handler:

1:
    b 1b
