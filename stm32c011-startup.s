.syntax unified
.cpu cortex-m0plus
.thumb

.global Reset_Handler
.global Default_Handler
.global SysTick_Handler
.global EXTI4_15_IRQHandler

.section .isr_vector,"a",%progbits
.align 2

/* Core exception vectors */
.word 0x20001800          /* Initial SP: 6 KB RAM */
.word Reset_Handler       /* 1  Reset */
.word Default_Handler     /* 2  NMI */
.word Default_Handler     /* 3  HardFault */
.word 0                   /* 4  Reserved */
.word 0                   /* 5  Reserved */
.word 0                   /* 6  Reserved */
.word 0                   /* 7  Reserved */
.word 0                   /* 8  Reserved */
.word 0                   /* 9  Reserved */
.word 0                   /* 10 Reserved */
.word Default_Handler     /* 11 SVC */
.word 0                   /* 12 Reserved */
.word 0                   /* 13 Reserved */
.word Default_Handler     /* 14 PendSV */
.word SysTick_Handler     /* 15 SysTick */

/* STM32C011 peripheral IRQ vectors */
.word Default_Handler     /* 16 WWDG              IRQ 0  */
.word 0                   /* 17 Reserved          IRQ 1  */
.word Default_Handler     /* 18 RTC               IRQ 2  */
.word Default_Handler     /* 19 FLASH             IRQ 3  */
.word Default_Handler     /* 20 RCC               IRQ 4  */
.word Default_Handler     /* 21 EXTI0_1           IRQ 5  */
.word Default_Handler     /* 22 EXTI2_3           IRQ 6  */
.word EXTI4_15_IRQHandler /* 23 EXTI4_15          IRQ 7  */
.word 0                   /* 24 Reserved          IRQ 8  */
.word Default_Handler     /* 25 DMA1_Channel1     IRQ 9  */
.word Default_Handler     /* 26 DMA1_Channel2_3   IRQ 10 */
.word Default_Handler     /* 27 DMAMUX1           IRQ 11 */
.word Default_Handler     /* 28 ADC1              IRQ 12 */
.word Default_Handler     /* 29 TIM1_BRK...       IRQ 13 */
.word Default_Handler     /* 30 TIM1_CC           IRQ 14 */
.word 0                   /* 31 Reserved          IRQ 15 */
.word Default_Handler     /* 32 TIM3              IRQ 16 */
/* ...remaining vectors can be added as needed... */

.section .text.Reset_Handler
.thumb_func

Reset_Handler:
    bl main

1:
    b 1b

.section .text.Default_Handler
.thumb_func

Default_Handler:
1:
    b 1b
