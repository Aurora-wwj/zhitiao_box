/* Host HAL substitutes for source-level LED tests; this is not a board test.
 * test_stm32_led_release.py inserts the supplied firmware's USER CODE 0 and
 * main body unchanged; its nonreturning entry is renamed to a host-only void
 * function so the embedded main special case is not required by the host C ABI.
 */
#include <assert.h>
#include <setjmp.h>
#include <stdint.h>
#include <stdio.h>
#include <string.h>

typedef enum { GPIO_PIN_RESET = 0, GPIO_PIN_SET = 1 } GPIO_PinState;
typedef struct { uint32_t output; } GPIO_TypeDef;
typedef struct { uint32_t Pin, Mode, Pull, Speed; } GPIO_InitTypeDef;
typedef struct { int unused; } UART_HandleTypeDef;

static GPIO_TypeDef port_a, port_c, port_d;
#define GPIOA (&port_a)
#define GPIOC (&port_c)
#define GPIOD (&port_d)
#define GPIO_PIN_1  (1u << 1)
#define GPIO_PIN_2  (1u << 2)
#define GPIO_PIN_8  (1u << 8)
#define GPIO_PIN_9  (1u << 9)
#define GPIO_PIN_10 (1u << 10)
#define GPIO_PIN_11 (1u << 11)
#define GPIO_PIN_12 (1u << 12)
#define GPIO_PIN_13 (1u << 13)
#define GPIO_PIN_14 (1u << 14)
#define GPIO_PIN_15 (1u << 15)
#define GPIO_MODE_OUTPUT_PP 1u
#define GPIO_NOPULL 0u
#define GPIO_SPEED_FREQ_LOW 0u

/* INSERT_PL_DEFINES */

static UART_HandleTypeDef huart2;
static unsigned clock_c, clock_d, configured_c, configured_d;
static unsigned toggles, delays, uart_frames, led_writes;
static jmp_buf stop_loop;
#define __HAL_RCC_GPIOC_CLK_ENABLE() ((void)++clock_c)
#define __HAL_RCC_GPIOD_CLK_ENABLE() ((void)++clock_d)

static void HAL_Init(void) { port_c.output = 0x55u; }
static void SystemClock_Config(void) { }
static void MX_GPIO_Init(void) { port_a.output = 0; }
static void MX_USART2_UART_Init(void) { }

static void HAL_GPIO_WritePin(GPIO_TypeDef *port, uint32_t pins, GPIO_PinState level)
{
    if (level == GPIO_PIN_SET) port->output |= pins;
    else port->output &= ~pins;
    if (port == GPIOC) {
        assert(pins == 0xff00u);
        ++led_writes;
        assert((port->output & 0xffu) == 0x55u);
    }
}

static void HAL_GPIO_Init(GPIO_TypeDef *port, const GPIO_InitTypeDef *init)
{
    assert(init->Mode == GPIO_MODE_OUTPUT_PP);
    assert(init->Pull == GPIO_NOPULL && init->Speed == GPIO_SPEED_FREQ_LOW);
    if (port == GPIOC) { assert(init->Pin == 0xff00u); configured_c = 1; }
    else { assert(port == GPIOD && init->Pin == GPIO_PIN_2); configured_d = 1; }
}

static GPIO_PinState HAL_GPIO_ReadPin(const GPIO_TypeDef *port, uint32_t pins)
{
    return (port->output & pins) ? GPIO_PIN_SET : GPIO_PIN_RESET;
}

static void HAL_GPIO_TogglePin(GPIO_TypeDef *port, uint32_t pins)
{
    assert(port == GPIOA && pins == GPIO_PIN_1);
    port->output ^= pins;
    ++toggles;
}

static int HAL_UART_Transmit(UART_HandleTypeDef *uart, const uint8_t *message,
                             uint16_t count, uint32_t timeout)
{
    assert(uart == &huart2 && timeout == 100);
    assert(count == 12 && memcmp(message, "ZHIDIAO_OK\r\n", count) == 0);
    ++uart_frames;
    return 0;
}

static void HAL_Delay(uint32_t milliseconds)
{
    assert(milliseconds == 500 && clock_c == 1 && clock_d == 1);
    assert(configured_c && configured_d && (port_d.output & GPIO_PIN_2));
    assert(led_writes == toggles + 2); /* preload, initial mirror, then each toggle */
    assert((port_c.output & 0xff00u) ==
           ((port_a.output & GPIO_PIN_1) ? 0u : 0xff00u));
    assert((port_c.output & 0xffu) == 0x55u);
    if (++delays == 8) longjmp(stop_loop, 1);
}

/* INSERT_HELPERS */

/* INSERT_FIRMWARE_MAIN */

int main(void)
{
    if (setjmp(stop_loop) == 0) firmware_main();
    assert(toggles == 8 && delays == 8 && uart_frames == 2);
    puts("LED_HOST_CHECKS_PASSED: 8 toggles, 8 LEDs, active-low mirror, 500 ms delays, 2 UART frames");
    return 0;
}
