// SPDX-License-Identifier: MIT
// One bounded low-strength pulse; no global gain or calibration changes.
#include <errno.h>
#include <fcntl.h>
#include <linux/input.h>
#include <signal.h>
#include <stdio.h>
#include <string.h>
#include <sys/file.h>
#include <sys/ioctl.h>
#include <time.h>
#include <unistd.h>

static volatile sig_atomic_t interrupted;
static void stop(int sig) { (void)sig; interrupted = 1; }
int main(int argc, char **argv) {
    if (argc != 2) { fprintf(stderr, "usage: myron-haptic-probe /dev/input/eventN\n"); return 2; }
    int fd = open(argv[1], O_RDWR | O_CLOEXEC | O_NOFOLLOW);
    if (fd < 0) { perror("open"); return 1; }
    char name[128] = {0};
    unsigned char bits[(FF_MAX + 8) / 8] = {0};
    if (flock(fd, LOCK_EX | LOCK_NB) || ioctl(fd, EVIOCGNAME(sizeof(name)), name) < 0 ||
        strcmp(name, "qcom-hv-haptics") || ioctl(fd, EVIOCGBIT(EV_FF, sizeof(bits)), bits) < 0 ||
        !(bits[FF_CONSTANT / 8] & (1U << (FF_CONSTANT % 8)))) {
        fprintf(stderr, "refused: expected idle qcom-hv-haptics with FF_CONSTANT\n"); close(fd); return 1;
    }
    signal(SIGTERM, stop); signal(SIGINT, stop);
    struct ff_effect effect = {0};
    effect.type = FF_CONSTANT; effect.id = -1;
    effect.u.constant.level = 4096;
    effect.replay.length = 80;
    if (ioctl(fd, EVIOCSFF, &effect) < 0) { perror("upload"); close(fd); return 1; }
    struct input_event event = {0};
    event.type = EV_FF; event.code = effect.id; event.value = 1;
    int result = 0;
    if (!interrupted && write(fd, &event, sizeof(event)) == sizeof(event)) {
        struct timespec delay = {.tv_sec = 0, .tv_nsec = 150000000};
        nanosleep(&delay, NULL);
    } else { perror("play"); result = 1; }
    event.value = 0;
    if (write(fd, &event, sizeof(event)) != sizeof(event)) { perror("stop"); result = 1; }
    if (ioctl(fd, EVIOCRMFF, effect.id) < 0) { perror("erase"); result = 1; }
    close(fd);
    if (!result) puts("pulse=80ms strength=4096/32767 stopped=yes erased=yes; physical confirmation required");
    return result;
}
