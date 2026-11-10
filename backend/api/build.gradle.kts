plugins {
    kotlin("jvm") version "2.4.10"
    kotlin("plugin.allopen") version "2.4.10"
    kotlin("plugin.serialization") version "2.4.10"
    id("io.quarkus")
    id("nu.studer.jooq") version "10.1.1"
}

repositories {
    mavenCentral()
    mavenLocal()
}

val quarkusPlatformGroupId: String by project
val quarkusPlatformArtifactId: String by project
val quarkusPlatformVersion: String by project

dependencies {
    implementation(enforcedPlatform("${quarkusPlatformGroupId}:${quarkusPlatformArtifactId}:${quarkusPlatformVersion}"))
    implementation("io.quarkus:quarkus-info")
    implementation("io.quarkus:quarkus-config-yaml")
    implementation("io.quarkus:quarkus-smallrye-health")
    implementation("io.quarkus:quarkus-jdbc-postgresql")
    implementation("io.quarkus:quarkus-micrometer")
    implementation("io.quarkus:quarkus-micrometer-registry-prometheus")
    implementation("io.quarkus:quarkus-quartz")
    implementation("io.quarkus:quarkus-oidc")
    implementation("io.quarkus:quarkus-mailer")
    implementation("io.quarkus:quarkus-liquibase")
    implementation("org.mindrot:jbcrypt:0.4")
    implementation("io.quarkiverse.quinoa:quarkus-quinoa:2.9.2")
    implementation("org.citrusframework:citrus-quarkus:5.0.2")
    testImplementation("io.quarkus:quarkus-junit5-mockito")

    implementation("io.quarkus:quarkus-grpc")
    implementation("io.quarkus:quarkus-rest")
    implementation("io.quarkiverse.jooq:quarkus-jooq:2.2.0")
    implementation("io.quarkus:quarkus-kotlin")
    implementation("io.quarkus:quarkus-smallrye-graphql")
    implementation("io.quarkus:quarkus-rest-kotlin-serialization")
    implementation("org.jetbrains.kotlin:kotlin-stdlib-jdk8")
    implementation("io.quarkus:quarkus-arc")
    testImplementation("io.quarkus:quarkus-junit")
    testImplementation("io.rest-assured:rest-assured")

    jooqGenerator("org.postgresql:postgresql:42.7.14")
    implementation("org.jetbrains.kotlinx:kotlinx-serialization-json:1.11.0")
}

group = "ru.dirtydocs"
version = "1.0"

java {
    sourceCompatibility = JavaVersion.VERSION_21
    targetCompatibility = JavaVersion.VERSION_21
}

allOpen {
    annotation("jakarta.ws.rs.Path")
    annotation("jakarta.enterprise.context.ApplicationScoped")
    annotation("jakarta.persistence.Entity")
    annotation("io.quarkus.test.junit.QuarkusTest")
}

kotlin {
    compilerOptions {
        jvmTarget = org.jetbrains.kotlin.gradle.dsl.JvmTarget.JVM_21
        javaParameters = true
    }
}
