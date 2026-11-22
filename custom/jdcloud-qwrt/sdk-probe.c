#define _POSIX_C_SOURCE 200809L
#include <dlfcn.h>
#include <errno.h>
#include <pthread.h>
#include <stdio.h>
#include <stdlib.h>
#include <sys/file.h>
#include <time.h>
#include <unistd.h>
static void *worker(void *arg) { return arg; }
int main(void) {
    struct timespec ts;
    pthread_t thread;
    void *result = NULL;
    int marker = 1;
    FILE *lock = tmpfile();
    if (!lock || flock(fileno(lock), LOCK_EX | LOCK_NB)) return 10;
    if (clock_gettime(CLOCK_MONOTONIC, &ts)) return 11;
    if (pthread_create(&thread, NULL, worker, &marker)) return 12;
    if (pthread_join(thread, &result) || result != &marker) return 13;
    void *lib = dlopen("libc.so", RTLD_NOW);
    if (!lib || !dlsym(lib, "clock_gettime")) return 14;
    if (sizeof(void*) != 8 || sizeof(time_t) != 8 || sizeof(struct timespec) != 16) return 15;
    printf("{\"arch\":\"aarch64\",\"pointer_bytes\":%zu,\"time_t_bytes\":%zu,\"timespec_bytes\":%zu,\"pthread\":true,\"flock\":true,\"dlopen\":true,\"host\":\"qemu-sdk-sysroot\",\"qwrt_runtime_tested\":false}\n",sizeof(void*),sizeof(time_t),sizeof(struct timespec));
    dlclose(lib);
    fclose(lock);
    return 0;
}
