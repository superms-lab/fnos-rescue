#define _FILE_OFFSET_BITS 64
#define _GNU_SOURCE
#include <errno.h>
#include <fcntl.h>
#include <inttypes.h>
#include <stdint.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <sys/stat.h>
#include <time.h>
#include <unistd.h>

static unsigned char fsid[16];

static int parse_fsid(const char *text) {
    char hex[33];
    size_t n = 0;
    for (; *text; text++) {
        if (*text == '-') continue;
        if (n >= 32) return -1;
        hex[n++] = *text;
    }
    if (n != 32) return -1;
    hex[32] = '\0';
    for (size_t i = 0; i < 16; i++) {
        char pair[3] = { hex[i * 2], hex[i * 2 + 1], '\0' };
        char *end;
        unsigned long value = strtoul(pair, &end, 16);
        if (*end) return -1;
        fsid[i] = (unsigned char)value;
    }
    return 0;
}

static uint64_t le64(const unsigned char *p) {
    uint64_t v = 0;
    for (int i = 7; i >= 0; --i) v = (v << 8) | p[i];
    return v;
}

static double seconds_since(const struct timespec *start) {
    struct timespec now;
    clock_gettime(CLOCK_MONOTONIC, &now);
    return (now.tv_sec - start->tv_sec) + (now.tv_nsec - start->tv_nsec) / 1e9;
}

int main(int argc, char **argv) {
    if (argc < 3 || argc > 5) {
        fprintf(stderr, "usage: %s DEVICE FSID [START_GIB [END_GIB]]\n", argv[0]);
        return 2;
    }
    if (parse_fsid(argv[2])) {
        fprintf(stderr, "FSID must contain 32 hexadecimal digits\n");
        return 2;
    }
    int fd = open(argv[1], O_RDONLY | O_CLOEXEC);
    if (fd < 0) { perror("open"); return 1; }
    off_t size = lseek(fd, 0, SEEK_END);
    if (size < 0) { perror("lseek"); return 1; }
    const size_t step = 16384, chunk = 64UL << 20;
    unsigned char *buf = malloc(chunk);
    if (!buf) { perror("malloc"); return 1; }
    uint64_t start = argc == 4 ? strtoull(argv[3], NULL, 10) << 30 : 0;
    if (argc >= 4) start = strtoull(argv[3], NULL, 10) << 30;
    start -= start % step;
    uint64_t end = argc == 5 ? strtoull(argv[4], NULL, 10) << 30 : (uint64_t)size;
    if (end > (uint64_t)size) end = (uint64_t)size;
    end -= end % step;
    if (end <= start) {
        fprintf(stderr, "END_GIB must be greater than START_GIB\n");
        return 2;
    }
    struct timespec begun;
    clock_gettime(CLOCK_MONOTONIC, &begun);
    uint64_t next_report = start;
    uint64_t nodes = 0, root_tree_nodes = 0;
    for (uint64_t base = start; base < end; base += chunk) {
        size_t want = end - base < chunk ? (size_t)(end - base) : chunk;
        ssize_t got = pread(fd, buf, want, (off_t)base);
        if (got < 0) { fprintf(stderr, "pread at %" PRIu64 ": %s\n", base, strerror(errno)); return 1; }
        if (!got) break;
        for (size_t pos = 0; pos + 101 <= (size_t)got; pos += step) {
            unsigned char *h = buf + pos;
            if (memcmp(h + 32, fsid, 16) != 0) continue;
            nodes++;
            uint64_t logical = le64(h + 48);
            uint64_t generation = le64(h + 80);
            uint64_t owner = le64(h + 88);
            unsigned level = h[100];
            if (owner == 1) {
                printf("ROOT_TREE physical=%" PRIu64 " logical=%" PRIu64
                       " generation=%" PRIu64 " nritems=%u level=%u\n",
                       base + pos, logical, generation,
                       (unsigned)h[96] | ((unsigned)h[97] << 8) |
                       ((unsigned)h[98] << 16) | ((unsigned)h[99] << 24), h[100]);
                fflush(stdout);
                root_tree_nodes++;
            }
            if ((owner == 5 && level >= 1) || (owner >= 256 && level >= 2)) {
                printf("FS_CANDIDATE physical=%" PRIu64 " logical=%" PRIu64
                       " generation=%" PRIu64 " owner=%" PRIu64
                       " nritems=%u level=%u\n",
                       base + pos, logical, generation, owner,
                       (unsigned)h[96] | ((unsigned)h[97] << 8) |
                       ((unsigned)h[98] << 16) | ((unsigned)h[99] << 24), level);
                fflush(stdout);
            }
        }
        if (base >= next_report) {
            double elapsed = seconds_since(&begun);
            double done_gib = (base + got - start) / 1073741824.0;
            double total_gib = (end - start) / 1073741824.0;
            double mib_s = elapsed > 0 ? done_gib * 1024.0 / elapsed : 0;
            double eta_min = mib_s > 0 ? (total_gib - done_gib) * 1024.0 / mib_s / 60.0 : 0;
            fprintf(stderr, "PROGRESS %.1f/%.1f GiB (%.1f%%), %.0f MiB/s, ETA %.1f min, nodes=%" PRIu64 ", roots=%" PRIu64 "\n",
                    done_gib, total_gib, done_gib * 100.0 / total_gib, mib_s, eta_min,
                    nodes, root_tree_nodes);
            fflush(stderr);
            next_report = base + (10ULL << 30);
        }
    }
    fprintf(stderr, "DONE nodes=%" PRIu64 " roots=%" PRIu64 "\n",
            nodes, root_tree_nodes);
    return root_tree_nodes ? 0 : 3;
}
